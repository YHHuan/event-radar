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
  fixture.sourceNetwork = [
    { id: 'official', name: '官方節慶資料', url: 'https://example.com/official', lenses: ['folk'],
      mode: 'automatic', status: '每日更新', lastSuccess: '2026-10-05T10:20:00+08:00', count: 3, note: '官方日期' },
    { id: 'race', name: '特色賽事窗口', url: 'https://example.com/races', lenses: ['endurance'],
      mode: 'automatic', status: '更新失敗，保留近期資料', lastSuccess: '2026-10-04T10:20:00+08:00', count: 2, note: '保留近期公告' },
    { id: 'social', name: '地方廟會粉專', url: 'https://example.com/social', lenses: ['folk'],
      mode: 'manual', status: '人工追蹤', count: 0, note: '日期依廟方公告' },
    { id: 'unsafe', name: '不安全連結', url: 'javascript:alert(1)', lenses: ['folk'], mode: 'manual' },
  ];
  const discovery = await browser.newPage({ viewport: { width: 390, height: 844 } });
  discovery.on('pageerror', (error) => errors.push(`discovery: ${error.message}`));
  await discovery.route('**/events.json', (route) => route.fulfill({ json: fixture }));
  await discovery.goto(base, { waitUntil: 'networkidle' });
  await discovery.locator('#source-title').click();
  if (await discovery.locator('#source-items article').count() !== 3) throw new Error('source directory lost entries or accepted an unsafe URL');
  if (!(await discovery.locator('#source-items').textContent()).includes('更新失敗')) throw new Error('source failure was hidden');
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
  if (await discovery.locator('#source-items article').count() !== 2
    || !(await discovery.locator('#source-items').textContent()).includes('人工追蹤')) throw new Error('folk sources did not distinguish social/manual windows');
  if (!(await discovery.locator('.event-card__date').textContent()).includes('進行中')) throw new Error('ongoing festival was not marked');
  if (!(await discovery.locator('#annual-watchlist').isVisible())) throw new Error('annual watchlist is missing');
  if (await discovery.locator('#annual-watchlist button[data-action="calendar"]').count()) throw new Error('undated interest became a calendar entry');
  await discovery.locator('#views button[data-view="weekend"]').click();
  if (await discovery.locator('.event-card').count() !== 1) throw new Error('ongoing festival disappeared from this weekend');
  const discoveryWidth = await discovery.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
  if (discoveryWidth[0] > discoveryWidth[1] + 1) throw new Error('discovery mobile layout overflow');
  if (process.env.SCREENSHOT_DIR) await discovery.screenshot({ path: resolve(process.env.SCREENSHOT_DIR, 'folk-mobile.png'), fullPage: true });
  await discovery.close();

  // Distinct races can share an organizer calendar. An expired favorite must
  // retain its own identity when another race remains at that URL.
  const shared = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const oldRace = { ...makeEvent('retired-race', '已收藏的跨夜接力', 'endurance', '2026-10-10', '2026-10-11'),
    url: 'https://example.com/calendar', sharedSourceUrl: true };
  fixture.events = [{ ...makeEvent('different-race', '另一場百公里超馬', 'endurance', '2026-11-20', '2026-11-21'),
    url: oldRace.url, sharedSourceUrl: true }];
  await shared.route('**/events.json', (route) => route.fulfill({ json: fixture }));
  await shared.addInitScript((record) => localStorage.setItem('ake-event-radar:saved:v2',
    JSON.stringify({ version: 2, items: [record] })), oldRace);
  await shared.goto(base, { waitUntil: 'networkidle' });
  const preserved = await shared.evaluate(() => JSON.parse(localStorage.getItem('ake-event-radar:saved:v2')).items);
  if (preserved.length !== 1 || preserved[0].id !== 'retired-race') throw new Error('shared calendar replaced a saved race');
  await shared.close();

  // Independent sessions must survive filters, reloads, favorites and ICS.
  const series = { ...makeEvent('test-series', '大稻埕書店走讀（三場）', 'urban', '2026-10-17T15:00:00', '2026-11-14T17:00:00'),
    url: 'https://example.com/bookstore', venue: '郭怡美書店', performanceCount: 3,
    performances: ['2026-11-14', '2026-10-17', '2026-10-31'].map((day) => ({
      start: `${day}T15:00:00`, end: `${day}T17:00:00`, venue: '郭怡美書店',
    })) };
  const mixed = { ...makeEvent('test-mixed', '日夜不同場次', 'urban', '2026-10-17T19:00:00', '2026-10-31T12:00:00'),
    url: 'https://example.com/mixed', performanceCount: 2,
    performances: [
      { start: '2026-10-17T19:00:00', end: '2026-10-17T21:00:00' },
      { start: '2026-10-31T10:00:00', end: '2026-10-31T12:00:00' },
    ] };
  const neighbor = { ...makeEvent('test-neighbor', '另一場活動', 'urban', '2026-10-31T18:00:00', '2026-10-31T20:00:00'),
    url: 'https://example.com/neighbor' };
  const span = { ...makeEvent('test-span', '連續展覽', 'urban', '2026-10-29', '2026-11-02'),
    url: 'https://example.com/span' };
  const sessionFixture = { ...fixture, events: [series, neighbor, mixed, span] };
  const dates = await browser.newPage({ viewport: { width: 390, height: 844 } });
  dates.on('pageerror', (error) => errors.push(`dates: ${error.message}`));
  await dates.route('**/events.json', (route) => route.fulfill({ json: sessionFixture }));
  await dates.goto(`${base}?view=all`, { waitUntil: 'networkidle' });
  await dates.locator('#toggle-filters').click();
  await dates.locator('#when-filters [data-value="date"]').click();
  await dates.locator('#date-from').fill('2026-10-31');
  const ids = await dates.locator('.event-card').evaluateAll((cards) => cards.map((card) => card.dataset.id));
  if (ids.join() !== 'test-span,test-mixed,test-series,test-neighbor') throw new Error(`matching-session order incorrect: ${ids}`);
  await dates.locator('#search').fill('大稻埕');
  const seriesCard = dates.locator('[data-id="test-series"]');
  const sessionStarts = await seriesCard.locator('.event-session').evaluateAll((rows) => rows.map((row) => row.dataset.start));
  if (sessionStarts.join() !== '2026-10-17T15:00:00,2026-10-31T15:00:00,2026-11-14T15:00:00') {
    throw new Error('session list truncated or unsorted');
  }
  if (await seriesCard.locator('.event-session[data-matches="true"]').count() !== 1
    || !(await seriesCard.locator('.event-card__date').textContent()).includes('10/31')) {
    throw new Error('later session was not used in headline/filter');
  }
  if (!(await seriesCard.locator('.event-sessions').textContent()).includes('15:00–17:00')) throw new Error('session end time missing');
  await dates.reload({ waitUntil: 'networkidle' });
  if (await dates.locator('#date-from').inputValue() !== '2026-10-31'
    || await dates.locator('.event-card').count() !== 1) throw new Error('exact date URL failed round trip');
  await dates.locator('#date-from').fill('2026-10-24');
  if (await dates.locator('.event-card').count()) throw new Error('gap between bookstore sessions became an event');
  await dates.locator('#when-filters [data-value="range"]').click();
  await dates.locator('#date-from').fill('2026-10-18');
  await dates.locator('#date-to').fill('2026-11-14');
  if (await seriesCard.locator('.event-session[data-matches="true"]').count() !== 2) throw new Error('inclusive range missed its last day');
  await dates.reload({ waitUntil: 'networkidle' });
  if (await dates.locator('#date-to').inputValue() !== '2026-11-14') throw new Error('range URL failed round trip');
  const rangePromise = dates.waitForEvent('download');
  await seriesCard.locator('button[data-action="calendar"]').click();
  const rangeCalendar = await readFile(await (await rangePromise).path(), 'utf8');
  if ((rangeCalendar.match(/BEGIN:VEVENT/g) || []).length !== 2
    || rangeCalendar.includes('DTSTART;TZID=Asia/Taipei:20261017T150000')) throw new Error('calendar included a session outside the date range');
  await dates.locator('#date-to').fill('2026-10-17');
  if (!(await dates.locator('#date-error').isVisible()) || await dates.locator('.event-card').count()) throw new Error('reversed range silently returned events');
  await dates.locator('#when-filters [data-value="date"]').click();
  await dates.locator('#date-from').fill('2026-10-31');
  await dates.locator('#clear-search').click();
  await dates.locator('#period-filters [data-value="evening"]').click();
  if (await dates.locator('.event-card').count() !== 1
    || await dates.locator('.event-card').getAttribute('data-id') !== 'test-neighbor') {
    throw new Error('date and evening filters matched different sessions');
  }
  await dates.locator('#period-filters [data-value="all"]').click();
  await dates.locator('#when-filters [data-value="all"]').click();
  await dates.locator('#search').fill('大稻埕');
  const calendarPromise = dates.waitForEvent('download');
  await seriesCard.locator('button[data-action="calendar"]').click();
  const calendarDownload = await calendarPromise;
  const calendar = (await readFile(await calendarDownload.path(), 'utf8')).replace(/\r\n /g, '');
  if ((calendar.match(/BEGIN:VEVENT/g) || []).length !== 3
    || !calendar.includes('DTEND;TZID=Asia/Taipei:20261017T170000')
    || !calendar.includes('DTSTART;TZID=Asia/Taipei:20261114T150000')) throw new Error('ICS collapsed three sessions into one span');
  const uidLines = calendar.split('\r\n').filter((line) => line.startsWith('UID:'));
  if (new Set(uidLines).size !== 3) throw new Error('session calendar UIDs collide');
  const singlePromise = dates.waitForEvent('download');
  await seriesCard.locator('button[data-action="calendar-session"]').nth(1).click();
  const singleCalendar = await readFile(await (await singlePromise).path(), 'utf8');
  if ((singleCalendar.match(/BEGIN:VEVENT/g) || []).length !== 1
    || !singleCalendar.includes('DTSTART;TZID=Asia/Taipei:20261031T150000')) throw new Error('individual session calendar used wrong date');
  await seriesCard.locator('button[data-action="save"]').click();
  await dates.reload({ waitUntil: 'networkidle' });
  let savedSeries = await dates.evaluate(() => JSON.parse(localStorage.getItem('ake-event-radar:saved:v2')).items[0]);
  if (savedSeries.performances.length !== 3) throw new Error('saved event lost later sessions');
  // A saved series remains usable after the public feed no longer contains it.
  sessionFixture.events = [];
  await dates.goto(`${base}?view=saved&when=all`, { waitUntil: 'networkidle' });
  if (await dates.locator('.event-session').count() !== 3) throw new Error('expired saved series lost its sessions');
  await dates.locator('#toggle-filters').click();
  await dates.locator('#when-filters [data-value="date"]').click();
  await dates.locator('#date-from').fill('2026-11-14');
  if (new URL(dates.url()).searchParams.get('view') !== 'saved'
    || await dates.locator('.event-card').count() !== 1) throw new Error('date selector left favorites view');
  for (const width of [390, 1440]) {
    await dates.setViewportSize({ width, height: 1000 });
    const size = await dates.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    if (size[0] > size[1] + 1) throw new Error(`date controls overflow at ${width}`);
    if (process.env.SCREENSHOT_DIR) await dates.screenshot({ path: resolve(process.env.SCREENSHOT_DIR, `sessions-${width}.png`), fullPage: true });
  }
  await dates.goto(`${base}?view=saved&when=date&date=2026-02-31`, { waitUntil: 'networkidle' });
  if (!(await dates.locator('#date-error').isVisible()) || await dates.locator('.event-card').count()) throw new Error('invalid URL date rolled into another month');
  await dates.locator('#reset-filters').click();
  if (new URL(dates.url()).searchParams.has('date') || !(await dates.locator('#custom-dates').isHidden())) throw new Error('reset retained custom date');
  await dates.close();

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
