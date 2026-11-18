// 2026-11-18 - 스마트보카 - Edge 헤드리스(DevTools 프로토콜)로 M-02, M-03, M-05, M-06 화면 동작 점검 (1회성)
// 파일 위치: ai-agent/claude/261118_화면점검/script/browser_check.js
//
// 사용법 (사전 준비: 임시 DB로 앱을 5001 포트에 띄우고, Edge를 --remote-debugging-port=9333 으로 실행)
//   node browser_check.js
// 삭제 확인 창은 취소(accept: false)로 처리해 실제로 단어가 지워지지 않게 한다.

const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5001';
const DEVTOOLS = 'http://127.0.0.1:9333';
const OUT = path.join(__dirname, '..');
const results = [];

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
  const dialogs = [];

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
    } else if (message.method === 'Page.javascriptDialogOpening') {
      dialogs.push(message.params);
      send('Page.handleJavaScriptDialog', { accept: false });
    }
  };

  const evaluate = async (expression) => {
    const reply = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (reply.result.exceptionDetails) {
      throw new Error(JSON.stringify(reply.result.exceptionDetails));
    }
    return reply.result.result.value;
  };

  const waitFor = async (expression, timeoutMs = 5000) => {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
      try {
        if (await evaluate(expression)) return true;
      } catch (error) {
        // 페이지 이동 중에는 실행 문맥이 잠시 없을 수 있다. 다시 시도한다.
      }
      await sleep(20);
    }
    throw new Error(`시간 초과: ${expression}`);
  };

  const navigate = async (url) => {
    await send('Page.navigate', { url });
    await sleep(150);
    await waitFor('document.readyState === "complete"');
  };

  const shot = async (name) => {
    const reply = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(OUT, name), Buffer.from(reply.result.data, 'base64'));
  };

  const record = (item, status, detail) => {
    results.push({ item, status, detail });
    console.log(`${item}\t${status}\t${detail}`);
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // M-03, M-02: 학습 화면. 숫자 키 입력과 클릭 후 결과 표시 시간
  await navigate(`${BASE}/study`);
  await waitFor('document.querySelectorAll(".choice").length === 4');
  await shot('shot_01_study_question.png');

  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: '2', code: 'Digit2', windowsVirtualKeyCode: 50, text: '2' });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: '2', code: 'Digit2', windowsVirtualKeyCode: 50 });
  await waitFor('!!document.getElementById("result").textContent');
  const keyResult = await evaluate(`({
    text: document.getElementById("result").textContent,
    disabled: document.querySelectorAll(".choice:disabled").length,
    marked: document.querySelectorAll(".choice.correct, .choice.wrong").length
  })`);
  record(
    'M-03',
    keyResult.disabled === 4 && keyResult.marked >= 1 ? '통과' : '실패',
    `숫자 2 키로 제출됨. 결과 문구: "${keyResult.text}"`
  );
  await shot('shot_02_study_answered.png');

  // 다음 문제로 넘어간 뒤 클릭 응답 시간 측정
  await evaluate('document.getElementById("next").click(); "ok"');
  await waitFor('document.querySelectorAll(".choice").length === 4 && !document.getElementById("result").textContent');
  const clickMs = await evaluate(`(async () => {
    const button = document.querySelector(".choice");
    const start = performance.now();
    button.click();
    while (!document.getElementById("result").textContent) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    return performance.now() - start;
  })()`);
  record(
    'M-02',
    clickMs < 1000 ? '통과' : '실패',
    `보기 클릭부터 결과 문구 표시까지 ${clickMs.toFixed(1)} ms (브라우저, 로컬 서버)`
  );

  // M-05 보조: 다음 버튼이 결과 표시 뒤에 나타나는지
  const nextVisible = await evaluate('!document.getElementById("next").hidden');
  record('M-05', nextVisible ? '부분' : '실패', '답한 뒤 "다음" 버튼 표시 확인. 마지막 문제에서 완료 화면 이동은 API 점검에서 확인');

  // 화면 캡처: 밝은 화면
  await navigate(`${BASE}/`);
  await shot('shot_03_home_light.png');
  await navigate(`${BASE}/report`);
  await shot('shot_04_report_light.png');

  // 다크 모드 캡처
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
  await navigate(`${BASE}/`);
  await shot('shot_05_home_dark.png');
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }] });

  // M-06: 등록, 수정, 삭제(취소)
  await navigate(`${BASE}/words`);
  await waitFor('document.querySelector(".word-form")');
  const countBefore = await evaluate('document.querySelectorAll(".word-item").length');
  await evaluate(`(() => {
    document.querySelector('input[name="english"]').value = "zqcheckword";
    document.querySelector('input[name="meaning"]').value = "점검용단어";
    document.querySelector('.word-form button[type="submit"]').click();
    return "ok";
  })()`);
  await sleep(300);
  await waitFor('document.querySelector(".flash") !== null');
  const addFlash = await evaluate('document.querySelector(".flash").textContent');

  await navigate(`${BASE}/words`);
  await waitFor('document.querySelector(".word-item") !== null');
  const countAfterAdd = await evaluate('document.querySelectorAll(".word-item").length');
  await shot('shot_06_words.png');

  dialogs.length = 0;
  await evaluate(`(() => {
    const button = document.querySelector('.word-item button.danger');
    button.click();
    return "clicked";
  })()`).catch(() => undefined);
  await sleep(400);
  const confirmSeen = dialogs.find((dialog) => dialog.type === 'confirm');
  await navigate(`${BASE}/words`);
  const countAfterCancel = await evaluate('document.querySelectorAll(".word-item").length');

  const m06Ok =
    addFlash.includes('단어를 등록했습니다') &&
    countAfterAdd === countBefore + 1 &&
    confirmSeen !== undefined &&
    confirmSeen.message.includes('관련 학습 기록도 함께 삭제됩니다') &&
    countAfterCancel === countAfterAdd;
  record(
    'M-06',
    m06Ok ? '부분' : '실패',
    `등록 알림 "${addFlash.trim()}", 삭제 확인 창 "${confirmSeen ? confirmSeen.message : '없음'}", 취소 후 단어 수 유지 ${countAfterCancel === countAfterAdd}. 수정 저장은 API 점검에서 확인`
  );

  ws.close();
  fs.writeFileSync(path.join(OUT, 'browser_check_results.json'), JSON.stringify(results, null, 2), 'utf8');
}

main().catch((error) => {
  console.error('점검 실패:', error);
  process.exit(1);
});
