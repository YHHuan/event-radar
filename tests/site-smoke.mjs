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

  await mobile.evaluate(() => {
    Object.defineProperty(navigator, 'share', {
      configurable: true,
      value: async (payload) => { window.__favoriteShare = payload; },
    });
  });
  await mobile.locator('#share-saved').click();
  const sharedUrl = await mobile.evaluate(() => window.__favoriteShare?.url);
  if (!sharedUrl || !new URL(sharedUrl).searchParams.get('favorites')?.includes(savedId)) {
    throw new Error('favorites share link did not contain the saved event');
  }

  await mobile.close();

  const imported = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const importedUrl = new URL(sharedUrl);
  importedUrl.protocol = 'http:';
  importedUrl.hostname = '127.0.0.1';
  importedUrl.port = String(server.address().port);
  await imported.goto(importedUrl.toString(), { waitUntil: 'networkidle' });
  if (await imported.locator('.event-card').count() !== 1) throw new Error('shared favorites did not import in a fresh browser');
  if (await imported.locator('.event-card').first().getAttribute('data-id') !== savedId) {
    throw new Error('shared favorites imported the wrong event');
  }
  if ((await imported.locator('#saved-count').textContent()) !== '1') throw new Error('saved count did not update after import');
  await imported.close();

  const legacy = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await legacy.goto(base, { waitUntil: 'networkidle' });
  await legacy.evaluate((id) => {
    localStorage.clear();
    localStorage.setItem('ake-event-radar:saved:v1', JSON.stringify([id]));
  }, savedId);
  await legacy.reload({ waitUntil: 'networkidle' });
  const migrated = await legacy.evaluate(() => JSON.parse(localStorage.getItem('ake-event-radar:saved:v2') || '{}'));
  if (migrated.schema !== 'ake-event-radar-saved/v2' || migrated.items?.[0]?.id !== savedId) {
    throw new Error('v1 favorite did not migrate to a durable record');
  }
  await legacy.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem('ake-event-radar:saved:v2'));
    saved.items[0].id = `retired-${saved.items[0].id}`;
    localStorage.setItem('ake-event-radar:saved:v2', JSON.stringify(saved));
  });
  await legacy.reload({ waitUntil: 'networkidle' });
  const reconciled = await legacy.evaluate(() => JSON.parse(localStorage.getItem('ake-event-radar:saved:v2')));
  if (reconciled.items?.[0]?.id !== savedId) throw new Error('changed event ID did not reconcile from its saved identity');
  await legacy.close();

  const denied = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await denied.addInitScript(() => {
    Storage.prototype.setItem = () => { throw new DOMException('denied', 'SecurityError'); };
  });
  await denied.goto(base, { waitUntil: 'networkidle' });
  const deniedSave = denied.locator('button[data-action="save"]').first();
  await deniedSave.click();
  if (await deniedSave.getAttribute('aria-pressed') !== 'false') throw new Error('failed write left a false saved state');
  if ((await denied.locator('#save-status').getAttribute('data-kind')) !== 'error') throw new Error('failed write was not reported');
  await denied.close();

  // Fixed dates keep the new discovery checks independent of live announcements.
  const fixture = JSON.parse(await readFile(resolve(site, 'events.json'), 'utf8'));
  const example = fixture.events[0];
  const makeEvent = (id, title, lens, firstStart, lastEnd) => ({
    ...example, id, title, city: '台南市', tier: 'strong', image: '',
    firstStart, lastStart: firstStart, lastEnd, dateOnly: firstStart.length === 10,
    performanceCount: 1, performances: [{ start: firstStart, end: lastEnd, venue: '測試場地' }],
    lenses: [{ key: lens, label: { music_festival: '音樂祭', folk: '民俗祭典', endurance: '路跑三鐵' }[lens] }],
    checkedOn: '2026-10-05', registrationNote: '各組報名與比賽日期分開確認',
  });
  fixture.today = '2026-10-05';
  fixture.events = [
    makeEvent('test-music', '海邊音樂祭', 'music_festival', '2026-10-09T12:00:00', '2026-10-11T21:00:00'),
    makeEvent('test-folk', '進行中的媽祖遶境', 'folk', '2026-10-03', '2026-10-11'),
    makeEvent('test-race', '明年的特色三鐵', 'endurance', '2027-04-24', '2027-04-25'),
  ];
  fixture.watchlist = [{ id: 'test-annual', title: '鹽水蜂炮', lens: 'folk', city: '台南市',
    url: 'https://example.com/official', reason: '等待下一屆日期公告', checkedOn: '2026-10-05', status: '下一屆日期待確認' }];
  const discovery = await browser.newPage({ viewport: { width: 390, height: 844 } });
  discovery.on('pageerror', (error) => errors.push(`discovery: ${error.message}`));
  await discovery.route('**/events.json', (route) => route.fulfill({ json: fixture }));
  await discovery.goto(base, { waitUntil: 'networkidle' });
  for (const [lens, expected] of [['music_festival', 'test-music'], ['folk', 'test-folk'], ['endurance', 'test-race']]) {
    await discovery.locator(`#discovery-filters button[data-value="${lens}"]`).click();
    if (await discovery.locator('.event-card').count() !== 1
      || await discovery.locator('.event-card').getAttribute('data-id') !== expected) {
      throw new Error(`wrong discovery results for ${lens}`);
    }
    if (new URL(discovery.url()).searchParams.get('lens') !== lens
      || new URL(discovery.url()).searchParams.get('when') !== 'all') throw new Error('annual discovery URL was lost');
  }
  if (!(await discovery.locator('.event-card__date').textContent()).includes('2027')) throw new Error('future year is ambiguous');
  const allDayPromise = discovery.waitForEvent('download');
  await discovery.locator('button[data-action="calendar"]').click();
  const allDayDownload = await allDayPromise;
  const allDayText = await readFile(await allDayDownload.path(), 'utf8');
  if (!allDayText.includes('DTSTART;VALUE=DATE:20270424') || !allDayText.includes('DTEND;VALUE=DATE:20270426')) {
    throw new Error('all-day festival calendar did not use an exclusive end');
  }
  await discovery.locator('button[data-action="save"]').click();
  await discovery.reload({ waitUntil: 'networkidle' });
  const savedRace = await discovery.evaluate(() => JSON.parse(localStorage.getItem('ake-event-radar:saved:v2')).items[0]);
  if (savedRace.lastEnd !== '2027-04-25' || !savedRace.dateOnly || !savedRace.registrationNote) {
    throw new Error('saved race lost planning metadata');
  }
  await discovery.locator('#discovery-filters button[data-value="folk"]').click();
  if (!(await discovery.locator('.event-card__date').textContent()).includes('進行中')) throw new Error('ongoing festival was not marked');
  if (!(await discovery.locator('#annual-watchlist').isVisible())) throw new Error('annual watchlist is missing');
  if (await discovery.locator('#annual-watchlist button[data-action="calendar"]').count()) throw new Error('undated interest became a calendar entry');
  await discovery.locator('#views button[data-view="weekend"]').click();
  if (await discovery.locator('.event-card').count() !== 1) throw new Error('ongoing festival disappeared from this weekend');
  const discoveryWidth = await discovery.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
  if (discoveryWidth[0] > discoveryWidth[1] + 1) throw new Error('discovery mobile layout overflow');
  if (process.env.SCREENSHOT_DIR) await discovery.screenshot({ path: resolve(process.env.SCREENSHOT_DIR, 'folk-mobile.png'), fullPage: true });
  await discovery.close();

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
