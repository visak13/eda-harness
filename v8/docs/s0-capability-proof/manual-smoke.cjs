// Patched/headless Firefox fixture validation, NOT native-click acceptance.
const { firefox } = require('../../web/node_modules/playwright');
const { createServer } = require('./manual-server.cjs');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
(async () => {
  const server = createServer(); let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    browser = await firefox.launch({headless: true});
    const context = await browser.newContext();
    const origin = `http://127.0.0.1:${server.address().port}`;
    await context.grantPermissions(['notifications'], {origin});
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    await page.goto(origin);
    await page.waitForFunction(() => navigator.serviceWorker.controller);
    await page.locator('#draft').fill('S0 draft KEEP');
    const other = await context.newPage(); await other.goto(origin + '/?actor=B');
    await other.waitForFunction(() => navigator.serviceWorker.controller);
    const trial = randomUUID();
    await page.evaluate(data => navigator.serviceWorker.controller.postMessage({type:'synthetic-route', data}),
      {actor:'A', trial, destination:`request-s0-${trial}`, group:'synthetic-only'});
    await page.waitForFunction(() => document.getElementById('log').textContent.includes('"type": "outcome"'));
    const log = JSON.parse(await page.locator('#log').innerText());
    const outcome = log.find(entry => entry.type === 'outcome');
    assert.equal(outcome.synthetic, true);
    assert.equal(outcome.clientsBefore, 2); assert.equal(outcome.clientsAfter, 2);
    assert.equal(context.pages().length, 2);
    assert.equal(await page.locator('#draft').inputValue(), 'S0 draft KEEP');
    assert.equal(await other.locator('#destination').innerText(), 'none');
    if (outcome.outcome === 'reused') {
      await page.locator('#pending').waitFor({state:'visible'});
      assert.equal(await page.locator('#destination').innerText(), 'none');
      await page.locator('#pending').click();
      assert.equal(await page.locator('#destination').innerText(), `request-s0-${trial}`);
    } else assert.equal(outcome.outcome, 'focus_failed_no_new_tab');
    console.log(JSON.stringify({status:'fixture_smoke_pass', version:browser.version(), outcome,
      native_clicks:0, note:'synthetic dispatch cannot prove OS focus or installed Firefox'}, null, 2));
    await context.close();
  } catch (error) { console.error(error.message); process.exitCode = 1; }
  finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
})();
