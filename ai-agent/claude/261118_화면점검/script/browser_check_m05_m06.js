// 2026-11-18 - 스마트보카 - Edge 헤드리스로 M-05(마지막 문제 뒤 완료 화면), M-06(수정 저장) 클릭 검증 (1회성)
// 파일 위치: ai-agent/claude/261118_화면점검/script/browser_check_m05_m06.js
//
// 사용법 (사전 준비: 단어 5개짜리 임시 DB로 앱을 5002 포트에 띄우고, Edge를 9333 포트 DevTools로 실행)
//   node browser_check_m05_m06.js
// 임시 DB(%TEMP%\smartvoca_check2\check2.db)만 바뀐다. data/smartvoca.db 는 건드리지 않는다.

const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5002';
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

  // M-05: 세션을 끝까지 푼다. 틀리면 다시 나오므로 보기를 골라 가며 마지막 "다음"에서 완료 화면으로 가는지 본다.
  await navigate(`${BASE}/study`);
  await waitFor('document.querySelectorAll(".choice").length === 4');
  let answered = 0;
  let reachedDone = false;
  for (let attempt = 0; attempt < 200 && !reachedDone; attempt++) {
    await evaluate(`document.querySelectorAll(".choice")[${attempt % 4}].click(); "ok"`);
    await waitFor('!!document.getElementById("result").textContent');
    answered += 1;
    const isLastQuestion = await evaluate('!document.getElementById("next").hidden && document.getElementById("hint").textContent.includes("Enter")');
    if (!isLastQuestion) continue;
    await evaluate('document.getElementById("next").click(); "ok"');
    await sleep(300);
    try {
      await waitFor('location.pathname === "/study/done" || (document.querySelectorAll(".choice").length === 4 && !document.getElementById("result").textContent)', 3000);
    } catch (error) {
      // 새 문제 대기 실패는 아래에서 판단한다.
    }
    reachedDone = (await evaluate('location.pathname')) === '/study/done';
  }
  if (reachedDone) {
    await waitFor('document.body.textContent.includes("오늘의 학습 완료")');
    await shot('shot_07_study_done.png');
    record('M-05', '통과', `마지막 "다음" 클릭 후 /study/done 이동, 완료 화면 표시 (응답 ${answered}회)`);
  } else {
    record('M-05', '실패', `완료 화면에 도달하지 못함 (응답 ${answered}회)`);
  }

  // M-06: 단어 관리에서 첫 단어의 뜻을 고치고 저장
  await navigate(`${BASE}/words`);
  await waitFor('document.querySelector(".word-item") !== null');
  await evaluate(`(() => {
    const input = document.querySelector('.word-item input[name="meaning"]');
    input.value = "사과(수정)";
    document.querySelector('.word-item button.save').click();
    return "ok";
  })()`);
  await sleep(300);
  await waitFor('document.querySelector(".flash") !== null');
  const flash = await evaluate('document.querySelector(".flash").textContent');
  await navigate(`${BASE}/words`);
  const saved = await evaluate('document.querySelector(".word-item input[name=\\"meaning\\"]").value');
  const m06Ok = flash.includes('단어를 수정했습니다') && saved === '사과(수정)';
  record('M-06', m06Ok ? '통과' : '실패', `저장 알림 "${flash.trim()}", 새로고침 후 뜻 "${saved}"`);
  await shot('shot_08_words_edited.png');

  ws.close();
  fs.writeFileSync(path.join(OUT, 'browser_check_m05_m06_results.json'), JSON.stringify(results, null, 2), 'utf8');
}

main().catch((error) => {
  console.error('점검 실패:', error);
  process.exit(1);
});
