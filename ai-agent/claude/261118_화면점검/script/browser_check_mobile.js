// 2026-11-18 - 스마트보카 - 모바일 폭(390px)에서 화면이 넘치는지 CDP로 확인 (1회성)
// 파일 위치: ai-agent/claude/261118_화면점검/script/browser_check_mobile.js
//
// 사용법 (사전 준비: 5006 포트에 앱, Edge를 9444 포트 DevTools로 헤드리스 실행)
//   node browser_check_mobile.js
// 확인 항목: 문서 가로 폭이 뷰포트를 넘는지(가로 스크롤 여부), 화면 캡처 저장.
// 끝에 Browser.close로 Edge를 정상 종료한다.

const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5006';
const DEVTOOLS = 'http://127.0.0.1:9444';
const OUT = path.join(__dirname, '..');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const targets = await (await fetch(`${DEVTOOLS}/json`)).json();
  const page = targets.find((target) => target.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  let nextId = 1;
  const pending = new Map();
  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const id = nextId++;
      pending.set(id, resolve);
      ws.send(JSON.stringify({ id, method, params }));
    });
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  };
  const evaluate = async (expression) => {
    const reply = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (reply.result.exceptionDetails) throw new Error(JSON.stringify(reply.result.exceptionDetails));
    return reply.result.result.value;
  };
  const navigate = async (url) => {
    await send('Page.navigate', { url });
    await sleep(300);
    for (let i = 0; i < 100; i++) {
      try {
        if ((await evaluate('document.readyState')) === 'complete') return;
      } catch (error) {
        // 이동 중에는 실행 문맥이 잠시 없을 수 있다.
      }
      await sleep(30);
    }
  };
  const shot = async (name) => {
    const reply = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(OUT, name), Buffer.from(reply.result.data, 'base64'));
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });

  const pages = [
    { path: '/', name: 'shot_mobile_home.png' },
    { path: '/study', name: 'shot_mobile_study.png' },
    { path: '/words', name: 'shot_mobile_words.png' },
    { path: '/report', name: 'shot_mobile_report.png' },
  ];
  const summary = [];
  for (const target of pages) {
    await navigate(`${BASE}${target.path}`);
    const metrics = await evaluate(`({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      overflow: document.documentElement.scrollWidth > window.innerWidth
    })`);
    await shot(target.name);
    summary.push({ page: target.path, ...metrics });
    console.log(`${target.path}\tviewport=${metrics.viewport}\tdocument=${metrics.documentWidth}\toverflow=${metrics.overflow}`);
  }

  fs.writeFileSync(path.join(OUT, 'browser_check_mobile_results.json'), JSON.stringify(summary, null, 2), 'utf8');
  await send('Browser.close');
  ws.close();
}

main().catch((error) => {
  console.error('점검 실패:', error);
  process.exit(1);
});
