// Регрессия: ожидание решения модели не является вызовом MCP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
function definition(name) {
  const start = source.indexOf(`function ${name}(`);
  return source.slice(start, source.indexOf('\nfunction ', start + 1));
}
const context = vm.createContext({document: {
  createElement(tag) { return {tag, children: [], append(...items) { this.children.push(...items); }}; }
}});
vm.runInContext(['mcpStatusLabel', 'visibleMcpArguments', 'createMcpCallsPanel'].map(definition).join('\n'), context);
for (const phase of ['thinking', 'starting', 'completed', 'error']) {
  assert.equal(context.createMcpCallsPanel([], {live: true, phase}), null);
}
assert.equal(context.createMcpCallsPanel(undefined), null);
for (const status of ['running', 'completed', 'error']) {
  const panel = context.createMcpCallsPanel([{server: 'project', name: 'get_git_branch', status}], {live: true});
  assert.equal(panel.children[1].children[0].textContent, '1. project → get_git_branch');
  assert.equal(panel.children[1].className, `mcp-call-row ${status}`);
}
console.log('MCP activity UI: empty activity hidden; real calls and statuses displayed.');
