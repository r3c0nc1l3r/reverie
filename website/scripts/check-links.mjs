// Headless crawl of the built site: every internal page, link, image, script and stylesheet
// must load under the /reverie base. Start `npm run preview` first.
// Usage: node scripts/check-links.mjs [baseUrl]   (default http://localhost:4321/reverie/)
import { chromium } from 'playwright';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const start = new URL(process.argv[2] ?? 'http://localhost:4321/reverie/');
const base = start.pathname.endsWith('/') ? start.pathname : `${start.pathname}/`;
const downloads = mkdtempSync(join(tmpdir(), 'reverie-docs-check-'));

const browser = await chromium.launch({ headless: true, downloadsPath: downloads });
const context = await browser.newContext({ acceptDownloads: false });
const page = await context.newPage();

const queue = [start.href];
const seen = new Set();
const checkedAssets = new Map();
const failures = [];

async function checkAsset(url, from) {
	if (!checkedAssets.has(url)) {
		const res = await context.request.get(url).catch((e) => ({ status: () => String(e) }));
		checkedAssets.set(url, res.status());
	}
	const status = checkedAssets.get(url);
	if (status !== 200) failures.push(`${status} ${url} (from ${from})`);
}

while (queue.length) {
	const url = queue.shift();
	const key = url.split('#')[0];
	if (seen.has(key)) continue;
	seen.add(key);

	const failed = [];
	page.removeAllListeners('response');
	page.on('response', (r) => {
		const u = new URL(r.url());
		if (u.origin === start.origin && r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
	});
	const res = await page.goto(key, { waitUntil: 'networkidle' });
	if (!res || res.status() !== 200) {
		failures.push(`${res?.status()} ${key}`);
		continue;
	}
	for (const f of failed) failures.push(`${f} (loaded by ${key})`);

	const refs = await page.$$eval('a[href], img[src], link[href], script[src], source[srcset]', (els) =>
		els.map((e) => ({
			tag: e.tagName.toLowerCase(),
			url: e.href || e.src || (e.srcset || '').split(' ')[0],
		})),
	);
	for (const { tag, url: ref } of refs) {
		if (!ref) continue;
		const u = new URL(ref, key);
		if (u.origin !== start.origin) continue;
		if (!u.pathname.startsWith(base)) {
			failures.push(`outside base ${u.pathname} (from ${key})`);
			continue;
		}
		if (tag === 'a' && !/\.[a-z0-9]+$/i.test(u.pathname)) {
			queue.push(u.href);
		} else {
			await checkAsset(u.href.split('#')[0], key);
		}
	}
}

await browser.close();
rmSync(downloads, { recursive: true, force: true });

console.log(`Checked ${seen.size} pages and ${checkedAssets.size} assets.`);
if (failures.length) {
	console.error(`${failures.length} problems:\n${[...new Set(failures)].join('\n')}`);
	process.exit(1);
}
console.log('No broken links or assets.');
