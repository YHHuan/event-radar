import { createServer } from 'node:http';
import { mkdir, readFile, stat } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';
import { chromium } from 'playwright';

const root = resolve(new URL('..', import.meta.url).pathname);
const site = resolve(root, '_site');
const types = {
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
};

async function localFile(pathname) {
  const clean = decodeURIComponent(pathname).replace(/^\/+/, '');
  let file = resolve(site, clean || 'index.html');
  if (!file.startsWith(site + sep) && file !== site) return null;
  try {
    if ((await stat(file)).isDirectory()) file = resolve(file, 'index.html');
    return { file, body: await readFile(file) };
  } catch {
    return null;
  }
}

const server = createServer(async (req, res) => {
  const found = await localFile(new URL(req.url, 'http://localhost').pathname);
  if (!found) { res.writeHead(404).end('not found'); return; }
  res.setHeader('Content-Type', types[extname(found.file)] || 'application/octet-stream');
  res.writeHead(200).end(found.body);
});
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const base = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({ headless: true });
const errors = [];

async function checkViewport(width, height, label) {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on('pageerror', (error) => errors.push(`${label}: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('Failed to load resource')) {
      errors.push(`${label}: ${message.text()}`);
    }
  });
  const response = await page.goto(base, { waitUntil: 'networkidle' });
  if (!response?.ok()) throw new Error(`${label}: homepage HTTP ${response?.status()}`);
  if ((await page.title()) !== '有空｜活動雷達') throw new Error(`${label}: unexpected title`);
  await page.locator('.event-card').first().waitFor({ state: 'visible' });
  if (await page.locator('.event-card').count() < 3) throw new Error(`${label}: fewer than three cards`);
  const viewport = await page.evaluate(() => ({
    width: innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    headerHeight: document.querySelector('.masthead')?.getBoundingClientRect().height,
    cardHeight: document.querySelector('.event-card')?.getBoundingClientRect().height,
  }));
  if (viewport.scrollWidth > viewport.width + 1) {
    throw new Error(`${label}: horizontal overflow ${viewport.scrollWidth}/${viewport.width}`);
  }
  if (!viewport.headerHeight || !viewport.cardHeight) throw new Error(`${label}: blank layout`);
  if (process.env.SCREENSHOT_DIR) {
    await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: resolve(process.env.SCREENSHOT_DIR, `${label}.png`), fullPage: true });
  }
  return page;
}

try {
  const mobile = await checkViewport(390, 844, 'home-mobile');

  await mobile.locator('#search').fill('台北蚤之市');
  await mobile.locator('.event-card').first().waitFor({ state: 'visible' });
  if (await mobile.locator('.event-card').count() !== 1) throw new Error('search did not narrow to one event');
  if (!(await mobile.locator('.event-card h3').textContent()).includes('台北蚤之市')) throw new Error('search returned wrong event');
  if (!new URL(mobile.url()).searchParams.get('q')) throw new Error('search state is not shareable');

  await mobile.locator('#clear-search').click();
  await mobile.locator('#toggle-filters').click();
  await mobile.locator('#period-filters button[data-value="evening"]').click();
  await mobile.locator('.event-card').first().waitFor({ state: 'visible' });
  const eveningStarts = await mobile.locator('.event-card').evaluateAll((cards) => cards.map((card) => card.dataset.start));
  if (!eveningStarts.length || eveningStarts.some((value) => Number(value.slice(11, 13)) < 18)) {
    throw new Error('evening filter returned a daytime event');
  }
  if (new URL(mobile.url()).searchParams.get('period') !== 'evening') {
    throw new Error('period filter state is not shareable');
  }
  await mobile.locator('#period-filters button[data-value="all"]').click();
  await mobile.locator('#toggle-filters').click();
  const firstSave = mobile.locator('button[data-action="save"]').first();
  await firstSave.click();
  const savedId = await mobile.locator('.event-card').first().getAttribute('data-id');
  await mobile.reload({ waitUntil: 'networkidle' });
  const savedCard = mobile.locator(`.event-card[data-id="${savedId}"]`);
  if (await savedCard.locator('button[data-action="save"]').getAttribute('aria-pressed') !== 'true') {
    throw new Error('saved event did not persist');
  }

  const downloadPromise = mobile.waitForEvent('download');
  await savedCard.locator('button[data-action="calendar"]').click();
  const download = await downloadPromise;
  if (!download.suggestedFilename().endsWith('.ics')) throw new Error('calendar export is not ICS');

  await savedCard.locator('button[data-action="hide"]').click();
  if (await mobile.locator(`.event-card[data-id="${savedId}"]`).count()) throw new Error('hide did not remove card');
  await mobile.locator('#toggle-filters').click();
  await mobile.locator('#restore-hidden').click();
  if (!(await mobile.locator(`.event-card[data-id="${savedId}"]`).count())) throw new Error('restore hidden failed');

  await mobile.close();
  const desktop = await checkViewport(1440, 1000, 'home-desktop');
  await desktop.close();

  const status = JSON.parse(await readFile(resolve(site, 'site-status.json'), 'utf8'));
  if (status.counts.count < 30 || Object.keys(status.counts.sources).length < 2) throw new Error('status health is too small');
  if (errors.length) throw new Error(`browser errors: ${errors.join(' | ')}`);
  console.log(`smoke OK: ${status.counts.count} events from ${Object.keys(status.counts.sources).length} sources`);
} finally {
  await browser.close();
  await new Promise((ok) => server.close(ok));
}
