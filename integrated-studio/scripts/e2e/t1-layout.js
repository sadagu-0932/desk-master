const { connect, S, notifications } = require('./lib.js');
(async () => {
  const { b, p } = await connect();
  await p.waitForTimeout(6000);
  const r = await p.evaluate(() => {
    const txt = s => [...document.querySelectorAll(s)].map(e => e.textContent.trim());
    return {
      title: document.title,
      bodyBg: getComputedStyle(document.querySelector('.monaco-workbench, body')).backgroundColor,
      editorBg: getComputedStyle(document.body).getPropertyValue('--theia-editor-background'),
      font: getComputedStyle(document.body).fontFamily.slice(0, 40),
      explorerParts: txt('#explorer-view-container .theia-view-container-part-title .label, #explorer-view-container .part > .theia-header .label'),
      topBar: txt('#theia-top-panel .studio-run-bar-inner')[0],
      bottomTabs: txt('#theia-bottom-content-panel .lm-TabBar-tabLabel, #theia-bottom-content-panel .p-TabBar-tabLabel'),
      mainTabs: txt('#theia-main-content-panel .lm-TabBar-tabLabel, #theia-main-content-panel .p-TabBar-tabLabel'),
      status: txt('#theia-statusBar .element'),
      home: !!document.querySelector('.studio-home h1'),
    };
  });
  console.log(JSON.stringify(r, null, 1));
  console.log('알림:', await notifications(p));
  await p.screenshot({ path: S + '/shots/01-home.png' });
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
