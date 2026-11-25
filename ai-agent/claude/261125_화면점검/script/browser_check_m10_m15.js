// 2026-11-25 - 스마트보카 - Edge 헤드리스(DevTools 프로토콜)로 M-10~M-15 화면 동작 점검 (1회성)
// 파일 위치: ai-agent/claude/261125_화면점검/script/browser_check_m10_m15.js
//
// 사용법 (사전 준비: seed_check_db.py로 임시 DB를 만들고, 그 DB로 앱을 5001 포트에 띄우고,
//         Edge를 --remote-debugging-port=9333 으로 실행)
//   node browser_check_m10_m15.js
// 임시 DB만 쓰므로 실제 data/smartvoca.db는 바뀌지 않는다.

const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5001';
const DEVTOOLS = 'http://127.0.0.1:9333';
const OUT = path.join(__dirname, '..');
const results = [];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let ws;
let nextId = 1;
const pending = new Map();

function send(method, params = {}) {
  return new Promise((resolve) => {
    const id = nextId++;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const message = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (message.result.exceptionDetails) {
    throw new Error(message.result.exceptionDetails.exception?.description || 'evaluate 오류');
  }
  return message.result.result.value;
}

async function go(urlPath) {
  await send('Page.navigate', { url: BASE + urlPath });
  await sleep(900);
}

async function clickSubmit(formSelector) {
  await evaluate(`document.querySelector('${formSelector} button[type=submit]').click(), true`);
  await sleep(900);
}

async function screenshot(name) {
  const message = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(OUT, `shot_${name}.png`), Buffer.from(message.result.data, 'base64'));
}

function record(id, title, pass, detail) {
  results.push({ id, title, pass, detail });
  console.log(`${pass ? 'PASS' : 'FAIL'} ${id} ${title} — ${detail}`);
}

async function checkM10() {
  await go('/login');
  await evaluate(`
    document.querySelector('input[name=username]').value = 'tester';
    document.querySelector('input[name=password]').value = 'wrong-password';
    true`);
  await clickSubmit('form');
  const flashes = await evaluate(`[...document.querySelectorAll('.flash')].map(e => ({cls: e.className, text: e.textContent.trim()}))`);
  await screenshot('M10_login_error');
  const errorShown = flashes.some((f) => f.cls.includes('error') && f.text.startsWith('!') && f.text.includes('맞지 않습니다'));

  await go('/login');
  await evaluate(`
    document.querySelector('input[name=username]').value = 'tester';
    document.querySelector('input[name=password]').value = 'password123';
    true`);
  await clickSubmit('form');
  const path1 = await evaluate('location.pathname');
  const loggedIn = await evaluate(`document.querySelector('.logout-form') !== null`);
  record('M-10', '로그인 실패 알림 (!)', errorShown && path1 === '/' && loggedIn,
    `오류 알림 ${errorShown ? '표시' : '없음'}, 올바른 비밀번호 후 경로 ${path1}, 로그아웃 버튼 ${loggedIn ? '있음' : '없음'}`);
}

async function checkM11() {
  await go('/cards');
  const hiddenBefore = await evaluate(`document.getElementById('card-meaning').hidden === true`);
  await evaluate(`document.getElementById('card-reveal').click(), true`);
  await sleep(300);
  const shownAfterReveal = await evaluate(`document.getElementById('card-meaning').hidden === false`);
  await screenshot('M11_card_revealed');
  const indexBefore = await evaluate(`document.getElementById('card-index').textContent`);
  await evaluate(`document.getElementById('card-next').click(), true`);
  await sleep(300);
  const indexAfter = await evaluate(`document.getElementById('card-index').textContent`);
  const hiddenAgain = await evaluate(`document.getElementById('card-meaning').hidden === true`);
  record('M-11', '카드 뜻 숨김과 한 장씩 넘김', hiddenBefore && shownAfterReveal && hiddenAgain && indexBefore === '1' && indexAfter === '2',
    `처음 숨김 ${hiddenBefore}, 뜻 보기 후 표시 ${shownAfterReveal}, 다음 후 번호 ${indexBefore}→${indexAfter}, 다음 카드 뜻 숨김 ${hiddenAgain}`);
}

async function startExam(count, direction, form) {
  await go('/exam');
  await evaluate(`
    document.querySelector('select[name=count]').value = '${count}';
    document.querySelector('select[name=direction]').value = '${direction}';
    document.querySelector('select[name=form]').value = '${form}';
    true`);
  await clickSubmit('form[action="/exam"]');
  return evaluate('location.pathname');
}

async function checkM12() {
  const examPath = await startExam('5', 'en2ko', 'choice');
  const choiceCount = await evaluate(`document.querySelectorAll('.choices button').length`);
  const progressBefore = await evaluate(`document.querySelector('.progress').textContent.trim()`);
  await screenshot('M12_choice_question');
  await evaluate(`document.querySelector('.choices button').click(), true`);
  await sleep(900);
  const flash = await evaluate(`[...document.querySelectorAll('.flash')].map(e => e.textContent.trim()).join(' | ')`);
  const progressAfter = await evaluate(`document.querySelector('.progress') ? document.querySelector('.progress').textContent.trim() : ''`);
  await screenshot('M12_choice_answered');
  const graded = flash.includes('정답입니다.') || flash.includes('틀렸습니다.');
  record('M-12', '4지선다 채점 후 다음 문항', /^\/exam\/\d+$/.test(examPath) && choiceCount === 4 && graded && progressAfter.startsWith('2 / 5'),
    `경로 ${examPath}, 보기 ${choiceCount}개, 진행 ${progressBefore}→${progressAfter}, 알림 "${flash}"`);
}

async function checkM13() {
  const examPath = await startExam('5', 'ko2en', 'ox');
  const oButton = await evaluate(`!!document.querySelector('button[value=O]')`);
  const xButton = await evaluate(`!!document.querySelector('button[value=X]')`);
  const shownText = await evaluate(`document.querySelector('.example') ? document.querySelector('.example').textContent.trim() : ''`);
  const progressBefore = await evaluate(`document.querySelector('.progress').textContent.trim()`);
  await screenshot('M13_ox_question');
  await evaluate(`document.querySelector('button[value=O]').click(), true`);
  await sleep(900);
  const progressAfter = await evaluate(`document.querySelector('.progress') ? document.querySelector('.progress').textContent.trim() : ''`);
  record('M-13', 'OX 문항 버튼과 제시 뜻', /^\/exam\/\d+$/.test(examPath) && oButton && xButton && shownText.length > 0 && progressAfter.startsWith('2 / 5'),
    `경로 ${examPath}, O 버튼 ${oButton}, X 버튼 ${xButton}, 제시 문구 "${shownText}", 진행 ${progressBefore}→${progressAfter}`);
}

async function checkM14() {
  await go('/report');
  const dayLabel = await evaluate(`document.body.textContent.includes('현재 일차')`);
  const barWidth = await evaluate(`document.querySelector('.progress-bar span') ? document.querySelector('.progress-bar span').style.width : ''`);
  const trendRows = await evaluate(`[...document.querySelectorAll('table')].map(t => t.textContent).join(' ').includes('4지선다')`);
  const weakRows = await evaluate(`(() => { const h = [...document.querySelectorAll('h2')].find(e => e.textContent.includes('자주 틀리는')); if (!h) return 0; const table = h.parentElement.querySelector('tbody'); return table ? table.querySelectorAll('tr').length : 0; })()`);
  await screenshot('M14_report');
  record('M-14', '학습 기록 진도, 시험 추이, 자주 틀린 단어', dayLabel && barWidth !== '' && trendRows && weakRows > 0,
    `현재 일차 표시 ${dayLabel}, 진도 막대 ${barWidth || '없음'}, 4지선다 추이 ${trendRows}, 자주 틀린 단어 행 ${weakRows}개`);
}

async function checkM15() {
  await go('/settings');
  await evaluate(`document.querySelector('input[name=daily_target]').value = '12', true`);
  await clickSubmit('form[action="/settings"]');
  const flash = await evaluate(`[...document.querySelectorAll('.flash')].map(e => e.textContent.trim()).join(' | ')`);
  await go('/settings');
  const savedValue = await evaluate(`document.querySelector('input[name=daily_target]').value`);
  await screenshot('M15_settings');
  record('M-15', '설정 저장 후 유지', flash.includes('설정을 저장했습니다.') && savedValue === '12',
    `알림 "${flash}", 다시 연 뒤 하루 학습량 ${savedValue}`);
}

async function main() {
  const targets = await (await fetch(`${DEVTOOLS}/json`)).json();
  const page = targets.find((target) => target.type === 'page' && !target.url.startsWith('chrome-extension'));
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const resolve = pending.get(message.id);
      pending.delete(message.id);
      resolve(message);
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  const steps = [checkM10, checkM11, checkM12, checkM13, checkM14, checkM15];
  for (const step of steps) {
    try {
      await step();
    } catch (error) {
      const id = step.name.replace('check', 'M-').replace(/^M-(\d+)$/, 'M-$1');
      record(id, '실행 오류', false, error.message);
    }
  }

  fs.writeFileSync(path.join(OUT, 'browser_check_m10_m15_results.json'), JSON.stringify(results, null, 2));
  const failed = results.filter((r) => !r.pass).length;
  console.log(`\n총 ${results.length}개, 실패 ${failed}개`);
  ws.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
