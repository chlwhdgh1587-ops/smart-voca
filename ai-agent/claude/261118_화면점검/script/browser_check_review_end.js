// 2026-11-18 - 스마트보카 - 복습 블록에서 연속 3회 정답 시 결과 문구 확인 (1회성)
// 파일 위치: ai-agent/claude/261118_화면점검/script/browser_check_review_end.js
//
// 사용법 (사전 준비: apple의 연속 정답 2, 복습 대상으로 만든 임시 DB로 앱을 5003 포트에 띄우고, Edge를 9333 포트 DevTools로 실행)
//   node browser_check_review_end.js
// 임시 DB(%TEMP%\smartvoca_check3\check4.db)만 바뀐다.

const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5004';
const DEVTOOLS = 'http://127.0.0.1:9333';
const OUT = path.join(__dirname, '..');
const MEANINGS = { apple: '사과', banana: '바나나', cherry: '체리', grape: '포도', lemon: '레몬' };

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
  const waitFor = async (expression, timeoutMs = 5000) => {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
      try {
        if (await evaluate(expression)) return true;
      } catch (error) {
        // 페이지 이동 중에는 실행 문맥이 잠시 없을 수 있다.
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

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  await navigate(`${BASE}/study`);
  await waitFor('document.querySelectorAll(".choice").length === 4');
  const first = await evaluate(`({
    block: document.querySelector(".chip").textContent.trim(),
    english: document.querySelector(".english").textContent.trim()
  })`);
  if (first.block !== '복습' || first.english !== 'apple') {
    throw new Error(`첫 문제가 기대와 다름: ${JSON.stringify(first)}`);
  }

  // 아는 뜻을 골라 정답 제출 (apple 은 복습 블록에서 연속 3회째가 되어야 끝난다)
  const correctMeaning = MEANINGS[first.english];
  await evaluate(`(() => {
    const choice = Array.from(document.querySelectorAll(".choice")).find((button) => button.dataset.meaning === ${JSON.stringify(correctMeaning)});
    choice.click();
    return "ok";
  })()`);
  await waitFor('!!document.getElementById("result").textContent');
  const resultText = await evaluate('document.getElementById("result").textContent');
  const reply = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(OUT, 'shot_09_review_third_correct.png'), Buffer.from(reply.result.data, 'base64'));

  const ok = resultText.includes('복습이 끝났습니다');
  const summary = { english: first.english, block: first.block, streakBefore: 2, result: resultText, pass: ok };
  console.log(JSON.stringify(summary, null, 2));
  ws.close();
}

main().catch((error) => {
  console.error('점검 실패:', error);
  process.exit(1);
});
