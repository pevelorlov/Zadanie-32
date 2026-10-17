// Настоящий парсер: оформление, сохранение кода и опасные конструкции ответа.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const md = require('../static/markdown.js');
const render = md.render;
assert.match(render('**жирный** и *курсив* и __тоже жирный__'), /<strong>жирный<\/strong> и <em>курсив<\/em> и <strong>тоже жирный<\/strong>/);
assert.match(render('# Заголовок\n\n- Первый\n- Второй'), /<h1>Заголовок<\/h1>[\s\S]*<ul>[\s\S]*<li>Второй<\/li>/);
assert.match(render('1. Один\n2. Два\n\n> Цитата'), /<ol>[\s\S]*<blockquote>/);
assert.match(render('`**не жирный**`\n\n```python\nprint("<script>")\n```'), /<code>\*\*не жирный\*\*<\/code>[\s\S]*<pre><code class="language-python">print\(&quot;&lt;script&gt;&quot;\)/);
assert.match(render('| A | B |\n| --- | --- |\n| 1 | 2 |'), /<table>[\s\S]*<td>2<\/td>/);
assert.match(render('[Сайт](https://example.com "Пример")'), /href="https:\/\/example.com"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);
assert.match(render('одна строка\nдругая'), /одна строка<br>\nдругая/);
assert.match(render('\\*буквальные звёздочки\\*'), /\*буквальные звёздочки\*/);
assert.match(render('<script>alert(1)</script>\n<img src=x onerror=alert(1)>'), /&lt;script&gt;/);
for (const payload of [
  '<script>alert(1)</script>', '<svg onload=alert(1)>', '<iframe src=https://example.com>',
  '[x](javascript:alert%281%29)', '[x](JaVaScRiPt:alert%281%29)', '[x](javascript&#58;alert%281%29)',
  '[x](data:text/html;base64,PHNjcmlwdD4=)', '[x](file:///C:/secret)', '[x](vbscript:msgbox)',
  '[x](custom-app:execute)', '![следящий пиксель](https://example.com/tracker.png)',
]) {
  const html = render(payload);
  assert.doesNotMatch(html, /<(script|svg|iframe|img)\b/i);
  assert.doesNotMatch(html, /href="(?:javascript|vbscript|data|file|custom-app):/i);
}
// Проверяем также браузерную поставку и резервное отображение при сбое её загрузки.
const sandbox = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/vendor/markdown-it.min.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/markdown.js'), 'utf8'), sandbox);
assert.equal(sandbox.ChatMarkdown.render('**готово**'), '<p><strong>готово</strong></p>\n');
const fallback = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/markdown.js'), 'utf8'), fallback);
assert.equal(fallback.ChatMarkdown.render('<script>'), '&lt;script&gt;');
console.log('Markdown UI: formatting, code, tables, browser bundle and unsafe input checks passed.');
