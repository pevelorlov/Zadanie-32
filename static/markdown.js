/* Общий безопасный Markdown-рендерер для ответов. Оригинал остаётся в JSON. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("markdown-it"));
  else root.ChatMarkdown = factory(root.markdownit);
})(typeof globalThis !== "undefined" ? globalThis : this, function (MarkdownIt) {
  "use strict";
  const parser = MarkdownIt ? new MarkdownIt({
    html: false, breaks: true, linkify: false, typographer: false, maxNesting: 20,
  }) : null;
  if (parser) {
    const validateLink = parser.validateLink.bind(parser);
    parser.validateLink = href => validateLink(href)
      && (!/^[a-z][a-z\d+.-]*:/i.test(href) || /^(https?:|mailto:)/i.test(href));
    const linkOpen = parser.renderer.rules.link_open
      || ((tokens, index, options, env, renderer) => renderer.renderToken(tokens, index, options));
    parser.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
      tokens[index].attrSet("target", "_blank");
      tokens[index].attrSet("rel", "noopener noreferrer");
      return linkOpen(tokens, index, options, env, renderer);
    };
    // Ответ модели не должен сам инициировать сетевую загрузку изображений.
    parser.renderer.rules.image = (tokens, index) => parser.utils.escapeHtml(tokens[index].content || "Изображение");
  }
  function render(text) {
    const source = String(text ?? "");
    if (!parser) return source.replace(/[&<>"']/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
    return parser.render(source);
  }
  function renderInto(element, text) {
    element.classList.add("markdown-body");
    // raw HTML отключён, URL проверены парсером; произвольный HTML сюда не передаётся.
    element.innerHTML = render(text);
    element.querySelectorAll("table").forEach(table => {
      const wrapper = element.ownerDocument.createElement("div");
      wrapper.className = "markdown-table-scroll";
      wrapper.tabIndex = 0;
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("aria-label", "Таблица — прокрутка по горизонтали");
      table.replaceWith(wrapper);
      wrapper.append(table);
    });
  }
  return { render, renderInto };
});
