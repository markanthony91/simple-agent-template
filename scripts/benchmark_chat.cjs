// Two real Playground journeys; save metrics and paths, never message bodies/CPF.
const { chromium, expect } = require('/home/zerai/Sistemas/agent-chat-ui/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const runtime = 'https://langgraph-simple-agent-clean-production.up.railway.app';
const frontend = 'https://agent-chat-ui-fork-production.up.railway.app/';
const output = path.join(__dirname, '../docs/CHAT_BENCHMARK_RESULTS.json');

function navigationAudit(messages) {
  const directories = new Set(['']);
  const concepts = new Set();
  const pending = new Map();
  const checks = [];
  for (const message of messages) {
    for (const call of message.tool_calls || []) {
      pending.set(call.id, call);
      const a = call.args || {};
      if (call.name === 'okf_index') checks.push({tool: call.name, path: a.directory || '', exposed_before_call: directories.has(a.directory || '')});
      if (call.name === 'okf_search') checks.push({tool: call.name, scope: a.scope || '', exposed_before_call: directories.has(a.scope || '')});
      if (['okf_read', 'okf_read_section'].includes(call.name)) checks.push({tool: call.name, path: a.path, exposed_before_call: concepts.has(a.path)});
    }
    if (message.type !== 'tool') continue;
    const call = pending.get(message.tool_call_id);
    if (!call || !call.name.startsWith('okf_')) continue;
    const content = String(message.content || '');
    for (const line of content.split('\n')) {
      const target = line.startsWith('OKF_CHILD_DIRECTORIES:') ? directories : line.startsWith('OKF_CONCEPT_PATHS:') ? concepts : null;
      if (target) for (const match of line.matchAll(/`([^`]+)`/g)) target.add(match[1]);
      if (call.name === 'okf_search') {
        const match = line.match(/^([^\n]+\.md):\d+:/);
        if (match) concepts.add(match[1]);
      }
    }
    const base = call.name === 'okf_index' ? call.args.directory || '' : path.posix.dirname(call.args.path || '');
    for (const match of content.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)) {
      const link = match[1].split('#')[0];
      if (!link || /^(https?:|mailto:)/.test(link)) continue;
      const resolved = path.posix.normalize(/^(COMPANIES|GLOBAL|PRODUCTS|INSTITUTIONS)\//.test(link) ? link : path.posix.join(base, link)).replace(/\/$/, '');
      if (link.endsWith('/')) directories.add(resolved);
      else if (resolved.endsWith('.md')) concepts.add(resolved);
    }
  }
  return {checks, all_paths_previously_exposed: checks.every(x => x.exposed_before_call)};
}

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: '/nix/store/agamzskapmh5018k98bqfwrrb738bgpv-chromium-153.0.8010.52/bin/chromium', args: ['--no-sandbox']});
  const reports = [];
  try {
    for (const scenario of [{name: 'pix', text: 'Quero pagar à vista por PIX.'}, {name: 'boleto', text: 'Quero parcelar em 3 vezes no boleto.'}]) {
      const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
      const report = {scenario: scenario.name, started_at: new Date().toISOString(), turns: [], errors: [], requests: []};
      reports.push(report);
      page.on('pageerror', error => report.errors.push(error.message));
      page.on('requestfinished', request => {
        const url = new URL(request.url());
        if (url.origin === runtime && /\/runs|\/state|\/stream/.test(url.pathname)) report.requests.push({path: url.pathname, method: request.method(), timing: request.timing()});
      });
      const fixture = (await (await page.request.post(runtime + '/runs/wait', {data: {assistant_id: 'okf_admin', input: {operation: 'get_simulator_fixture'}}})).json()).result;
      await page.goto(frontend, {waitUntil: 'domcontentloaded'});
      const input = page.getByPlaceholder('Type your message...');
      await expect(input).toBeVisible({timeout: 30000});
      let count = 0;
      let messages = [];
      async function turn(text, label) {
        const at = new Date().toISOString();
        const start = performance.now();
        await input.fill(text);
        await page.getByRole('button', {name: 'Send', exact: true}).click();
        await expect(page.getByRole('button', {name: 'Cancel', exact: true})).toBeVisible({timeout: 15000});
        await expect(page.getByRole('button', {name: 'Cancel', exact: true})).toHaveCount(0, {timeout: 180000});
        const uiMs = performance.now() - start;
        report.thread_id = new URL(page.url()).searchParams.get('threadId');
        messages = (await (await page.request.get(runtime + '/threads/' + report.thread_id + '/state')).json()).values.messages;
        const delta = messages.slice(count); count = messages.length;
        const calls = delta.flatMap(m => (m.tool_calls || []).map(c => ({name: c.name, id: c.id, args: c.name.startsWith('okf_') ? c.args : undefined})));
        const outcomes = delta.filter(m => m.type === 'tool' && ['verify_and_get_customer', 'generate_payment_offer'].includes(m.name)).map(m => {
          const data = JSON.parse(m.content);
          return {name: m.name, verified: data.verified, created: data.created, reason: data.reason};
        });
        const result = {label, started_at: at, finished_at: new Date().toISOString(), ui_ms: Math.round(uiMs), with_state_inspection_ms: Math.round(performance.now() - start), calls, outcomes};
        report.turns.push(result);
        console.log(JSON.stringify({scenario: scenario.name, ...result}));
        return result;
      }
      await turn('Olá, tenho uma pendência e quero negociar.', 'opening');
      await turn(String(fixture.cpf).slice(0, 3), 'identity');
      let last = await turn(scenario.text, 'offer');
      if (!last.outcomes.some(x => x.created || x.reason)) last = await turn(scenario.name === 'pix' ? 'Sim, pode gerar a proposta à vista por PIX.' : 'Sim, pode gerar em 3 parcelas no boleto.', 'confirmation');
      report.navigation = navigationAudit(messages);
      report.created = report.turns.some(t => t.outcomes.some(x => x.created));
      report.finished_at = new Date().toISOString();
      fs.writeFileSync(output, JSON.stringify(reports, null, 2));
      console.log(JSON.stringify({scenario: scenario.name, thread_id: report.thread_id, created: report.created, navigation: report.navigation}));
      await page.close();
    }
  } finally {
    await browser.close();
    fs.writeFileSync(output, JSON.stringify(reports, null, 2));
  }
})();
