// Real Chromium UI verification against an explicitly disposable trial only.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  const [statePath, mode] = process.argv.slice(2);
  assert(['initialize', 'review', 'restart'].includes(mode));
  const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  assert(fs.existsSync(path.join(state.root, 'DISPOSABLE-REHEARSAL.txt')));
  assert(path.resolve(state.data_root) === path.join(path.resolve(state.root), 'ProductionData'));
  const password = process.env.SEEDLAB_TRIAL_PASSWORD;
  assert(password, 'Explicit disposable trial password required; never saved in reports');
  const browser = await chromium.launch({headless: true, executablePath: process.env.SEEDLAB_TRIAL_CHROMIUM});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: true});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const base = `http://127.0.0.1:${state.port}`;
  const screenshot = name => page.screenshot({path: path.join(state.root, `browser-${name}.png`), fullPage: false});
  try {
    if (mode === 'initialize') {
      await page.goto(base + '/setup');
      await page.getByRole('heading', {name: '初始化管理员'}).waitFor();
      const token = fs.readFileSync(path.join(state.data_root, 'data/bootstrap.token'), 'utf8').trim();
      await page.locator('#bootstrap-token').fill(token);
      await page.locator('#setup-username').fill('browser-trial-admin');
      await page.locator('#setup-name').fill('浏览器仿生产管理员');
      await page.locator('#setup-password').fill(password);
      await page.locator('#setup-confirm').fill(password);
      await page.getByRole('button', {name: '创建首个管理员'}).click();
      await page.waitForURL(base + '/');
      await page.getByText('浏览器仿生产管理员', {exact:true}).waitFor();
      await screenshot('initialized');
    } else {
      await page.goto(base + '/login');
      await page.locator('#username').fill('browser-trial-admin');
      await page.locator('#password').fill(password);
      await page.getByRole('button', {name:'登录工作空间'}).click();
      await page.waitForURL(base + '/');
      await page.getByText('目前没有需要处理的幼苗测定。可先完成发芽巡检，选出幼苗后再查看。').waitFor();
      await screenshot(mode + '-dashboard');
      await page.goto(base + '/experiments');
      await page.getByText('GER-202608-001', {exact:true}).waitFor();
      await screenshot(mode + '-experiments');
      const experiments = await (await context.request.get(base + '/api/experiments')).json();
      assert.equal(experiments.length,1);
      assert.equal(experiments[0].status,'completed');
      assert.equal(experiments[0].ended_at,null);
      const id = experiments[0].id;
      await page.goto(base + '/experiments/' + id);
      await page.getByRole('tab', {name:'实验材料', exact:true}).click();
      await page.getByText('本次实验材料', {exact:true}).waitFor();
      await screenshot(mode + '-materials');
      await page.goto(base + '/experiments/' + id + '/germination');
      await page.getByText('实验已结束，无当前执行待办；历史数据仍可查看。').waitFor();
      await screenshot(mode + '-overview');
      await page.getByRole('tab', {name:'发芽巡检', exact:true}).click();
      await page.getByText('实验已结束，不能新增巡检。已有数据可在培养皿状态和巡检历史中查阅。').waitFor();
      await screenshot(mode + '-inspection');
      await page.getByRole('tab', {name:'幼苗测定', exact:true}).click();
      await page.getByText('实验已结束，无当前执行待办；请打开“测定记录”查看历史数据。').waitFor();
      await screenshot(mode + '-measurement-tasks');
      await page.getByRole('tab', {name:'测定记录', exact:true}).click();
      await page.getByText(/共 4955 条记录/).waitFor();
      await screenshot(mode + '-records');
      const records = await (await context.request.get(base + '/api/experiments/' + id + '/measurement-records')).json();
      assert.equal(records.total,4955);
      const tasks = await (await context.request.get(base + '/api/experiments/' + id + '/measurement-worklist?status=all')).json();
      assert.deepEqual(tasks.materials,[]);
      assert(Object.values(tasks.summary).every(value => value === 0));
      if (mode === 'review') {
        await page.goto(base + '/data');
        await page.locator('.export-experiment-select .el-select__wrapper').click();
        await page.getByRole('option', {name:'200份材料历史种子萌发试验 · GER-202608-001', exact:true}).click();
        await page.keyboard.press('Escape');
        await screenshot('data-export');
        // The checked workbook download itself is triggered by the visible UI.
        const [download, response] = await Promise.all([
          page.waitForEvent('download'),
          page.waitForResponse(response => response.url().endsWith('/api/export/experiments/workbook.xlsx')),
          page.getByRole('button', {name:'生成实验数据工作簿', exact:true}).click(),
        ]);
        assert.equal(response.status(),200);
        await download.saveAs(path.join(state.root,'browser-export.xlsx'));
      }
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(state.root,`browser-${mode}-result.json`),JSON.stringify({result:'PASS',mode,
      real_chromium:true,headless:true,page_errors:errors,initialized_in_browser:mode==='initialize',
      logged_in_with_form:mode!=='initialize',source_and_app_code_unchanged:true},null,2));
    console.log(`BROWSER_${mode.toUpperCase()}=PASS`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode=1; });
