/**
 * Minimal but real fallback DOM implementation, used only if a test file
 * is run without `happy-dom` installed (e.g. `npm install` hasn't been run
 * yet). Implements actual working behavior for the DOM surface this
 * project's source files use: element creation, classList, dataset,
 * attributes, a real (if simplified) querySelector/querySelectorAll
 * engine with a basic HTML-fragment parser for innerHTML, event dispatch,
 * and a genuinely functional in-memory localStorage — not a pass-through
 * stub. Under the real `happy-dom` devDependency (the normal path via
 * `npm test`), this module is imported but never invoked — see the
 * `typeof document === 'undefined'` guard at the top of each test file.
 */

let _activeElement = null;
function setActiveElement(el) {
  _activeElement = el;
}
function getActiveElement() {
  return _activeElement;
}

const VOID_TAGS = new Set(["br", "hr", "img", "input", "meta", "link", "source", "wbr"]);

function parseHTMLFragment(html, ownerCreateElement) {
  const root = ownerCreateElement("div");
  const stack = [root];
  let i = 0;
  const n = html.length;

  function top() {
    return stack[stack.length - 1];
  }

  while (i < n) {
    const lt = html.indexOf("<", i);
    if (lt === -1) {
      const text = html.slice(i);
      if (text) top().appendChild(makeTextNode(text, ownerCreateElement));
      break;
    }
    if (lt > i) {
      const text = html.slice(i, lt);
      if (text) top().appendChild(makeTextNode(text, ownerCreateElement));
    }
    if (html.startsWith("<!--", lt)) {
      const end = html.indexOf("-->", lt);
      i = end === -1 ? n : end + 3;
      continue;
    }
    const gt = html.indexOf(">", lt);
    if (gt === -1) {
      break; // malformed tail; stop parsing rather than loop forever
    }
    const tagContent = html.slice(lt + 1, gt);
    i = gt + 1;

    if (tagContent.startsWith("/")) {
      const closeName = tagContent.slice(1).trim().toLowerCase();
      for (let j = stack.length - 1; j > 0; j--) {
        if (stack[j].tagName.toLowerCase() === closeName) {
          stack.length = j;
          break;
        }
      }
      continue;
    }

    const selfClosing = tagContent.endsWith("/");
    const body = selfClosing ? tagContent.slice(0, -1) : tagContent;
    const m = body.match(/^([a-zA-Z0-9_-]+)([\s\S]*)$/);
    if (!m) continue;
    const tagName = m[1];
    const attrString = m[2] || "";
    const el = ownerCreateElement(tagName);

    const attrRe = /([a-zA-Z_:][a-zA-Z0-9_:.-]*)\s*(?:=\s*("([^"]*)"|'([^']*)'|[^\s"'=<>`]+))?/g;
    let am;
    while ((am = attrRe.exec(attrString))) {
      const aName = am[1];
      const aValue = am[3] !== undefined ? am[3] : am[4] !== undefined ? am[4] : am[2] !== undefined ? am[2] : "";
      el.setAttribute(aName, aValue);
    }

    top().appendChild(el);
    if (!selfClosing && !VOID_TAGS.has(tagName.toLowerCase())) {
      stack.push(el);
    }
  }
  return root;
}

function makeTextNode(text, ownerCreateElement) {
  const node = ownerCreateElement("#text");
  const entities = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: "\u00a0" };
  node._text = text.replace(/&(#?[a-zA-Z0-9]+);/g, (whole, ent) => (ent in entities ? entities[ent] : whole));
  return node;
}

class ClassList {
  constructor(el) {
    this._el = el;
    this._set = new Set();
  }
  add(...names) {
    for (const n of names) this._set.add(n);
    this._sync();
  }
  remove(...names) {
    for (const n of names) this._set.delete(n);
    this._sync();
  }
  toggle(name, force) {
    if (force === undefined) {
      if (this._set.has(name)) this._set.delete(name);
      else this._set.add(name);
    } else if (force) {
      this._set.add(name);
    } else {
      this._set.delete(name);
    }
    this._sync();
    return this._set.has(name);
  }
  contains(name) {
    return this._set.has(name);
  }
  _sync() {
    this._el._className = [...this._set].join(" ");
  }
  _setFromString(str) {
    this._set = new Set((str || "").split(/\s+/).filter(Boolean));
  }
  toString() {
    return [...this._set].join(" ");
  }
  [Symbol.iterator]() {
    return this._set[Symbol.iterator]();
  }
}

function matchesSimpleSelector(el, sel) {
  sel = sel.trim();
  if (sel === "*") return true;
  // Strip and separately check :not(...) — supports one :not() clause.
  const notMatch = sel.match(/:not\(([^)]+)\)/);
  let positiveSel = sel;
  let notSel = null;
  if (notMatch) {
    notSel = notMatch[1];
    positiveSel = sel.replace(notMatch[0], "");
  }
  // Combine: tag#id.class1.class2[attr=val]
  const m = positiveSel.match(/^([a-zA-Z0-9_-]*)((?:#[a-zA-Z0-9_-]+)?)((?:\.[a-zA-Z0-9_-]+)*)((?:\[[^\]]+\])*)$/);
  if (!m) return false;
  const [, tag, idPart, classPart, attrPart] = m;
  if (tag && el.tagName?.toLowerCase() !== tag.toLowerCase()) return false;
  if (idPart && el.id !== idPart.slice(1)) return false;
  if (classPart) {
    const classes = classPart.slice(1).split(".");
    for (const c of classes) if (!el.classList.contains(c)) return false;
  }
  if (attrPart) {
    const attrs = attrPart.match(/\[([^\]]+)\]/g) || [];
    for (const a of attrs) {
      const inner = a.slice(1, -1);
      const eqMatch = inner.match(/^([a-zA-Z0-9_-]+)=["']?([^"'\]]*)["']?$/);
      if (eqMatch) {
        if (el.getAttribute(eqMatch[1]) !== eqMatch[2]) return false;
      } else {
        if (!el.hasAttribute(inner)) return false;
      }
    }
  }
  if (notSel && matchesSimpleSelector(el, notSel)) return false;
  return true;
}

function matchesSelector(el, selector) {
  // Supports comma-separated alternatives ("a, b, c") and, within each
  // alternative, a single simple selector or a descendant combinator
  // chain ("a b c"). No support for >, +, ~ — this project's source
  // code doesn't use those.
  const alternatives = selector.split(",").map((s) => s.trim());
  if (alternatives.length > 1) {
    return alternatives.some((alt) => matchesSelector(el, alt));
  }
  const parts = selector.trim().split(/\s+/);
  // The rightmost part must match the element itself directly — it must
  // NOT walk up the ancestor chain (a single-part selector like "select"
  // should only match <select> elements, not an <option> just because
  // its ancestor happens to be a <select>).
  if (!matchesSimpleSelector(el, parts[parts.length - 1])) return false;
  // Each earlier part (if any) must match some strict ancestor, searching
  // progressively further up for each one.
  let current = el.parentNode;
  for (let i = parts.length - 2; i >= 0; i--) {
    let found = false;
    while (current) {
      if (matchesSimpleSelector(current, parts[i])) {
        found = true;
        break;
      }
      current = current.parentNode;
    }
    if (!found) return false;
    current = current.parentNode;
  }
  return true;
}

function queryAll(root, selector) {
  const results = [];
  function walk(node) {
    for (const child of node.children) {
      if (matchesSelector(child, selector)) results.push(child);
      walk(child);
    }
  }
  walk(root);
  return results;
}

class Style {
  setProperty(name, value) {
    this[name] = value;
  }
  getPropertyValue(name) {
    return this[name] ?? "";
  }
  removeProperty(name) {
    delete this[name];
  }
}

function camelToKebab(s) {
  return s.replace(/([A-Z])/g, "-$1").toLowerCase();
}
function kebabToCamel(s) {
  return s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

function makeDatasetProxy(el) {
  return new Proxy(
    {},
    {
      get(_target, prop) {
        return el._attrs.get(`data-${camelToKebab(String(prop))}`);
      },
      set(_target, prop, value) {
        el._attrs.set(`data-${camelToKebab(String(prop))}`, String(value));
        return true;
      },
      has(_target, prop) {
        return el._attrs.has(`data-${camelToKebab(String(prop))}`);
      },
      deleteProperty(_target, prop) {
        return el._attrs.delete(`data-${camelToKebab(String(prop))}`);
      },
      ownKeys(_target) {
        return [...el._attrs.keys()]
          .filter((k) => k.startsWith("data-"))
          .map((k) => kebabToCamel(k.slice(5)));
      },
      getOwnPropertyDescriptor(_target, prop) {
        if (el._attrs.has(`data-${camelToKebab(String(prop))}`)) {
          return { enumerable: true, configurable: true, value: el._attrs.get(`data-${camelToKebab(String(prop))}`) };
        }
        return undefined;
      },
    }
  );
}

class Element {
  constructor(tagName) {
    this.tagName = (tagName || "div").toUpperCase();
    this._className = "";
    this.classList = new ClassList(this);
    this.style = new Style();
    this._attrs = new Map();
    this.dataset = makeDatasetProxy(this);
    this.children = [];
    this.parentNode = null;
    this._listeners = new Map();
    this._text = "";
    this._html = "";
    this.value = "";
    this.disabled = false;
    this.checked = false;
  }

  get className() {
    return this._className;
  }
  set className(v) {
    this._className = v;
    this.classList._setFromString(v);
  }

  get textContent() {
    if (this.children.length === 0) return this._text;
    return this.children.map((c) => c.textContent).join("");
  }
  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }

  get innerHTML() {
    return this._html;
  }
  set innerHTML(v) {
    this._html = String(v);
    const fragment = parseHTMLFragment(this._html, (tag) => new Element(tag));
    this.children = fragment.children;
    for (const c of this.children) c.parentNode = this;
  }

  get firstChild() {
    return this.children[0] || null;
  }
  get lastChild() {
    return this.children[this.children.length - 1] || null;
  }
  get parentElement() {
    return this.parentNode;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  removeChild(child) {
    this.children = this.children.filter((c) => c !== child);
    child.parentNode = null;
    return child;
  }
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
  insertBefore(newNode, refNode) {
    const idx = this.children.indexOf(refNode);
    newNode.parentNode = this;
    if (idx === -1) this.children.push(newNode);
    else this.children.splice(idx, 0, newNode);
    return newNode;
  }
  cloneNode(deep) {
    const clone = new Element(this.tagName);
    clone.className = this.className;
    clone._attrs = new Map(this._attrs);
    clone._text = this._text;
    if (deep) clone.children = this.children.map((c) => c.cloneNode(true));
    return clone;
  }

  setAttribute(name, value) {
    this._attrs.set(name, String(value));
    if (name === "class") this.className = value;
    if (name === "id") this.id = value;
  }
  getAttribute(name) {
    return this._attrs.has(name) ? this._attrs.get(name) : null;
  }
  hasAttribute(name) {
    return this._attrs.has(name);
  }
  removeAttribute(name) {
    this._attrs.delete(name);
  }

  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, new Set());
    this._listeners.get(type).add(fn);
  }
  removeEventListener(type, fn) {
    this._listeners.get(type)?.delete(fn);
  }
  dispatchEvent(event) {
    event.target = event.target || this;
    for (const fn of this._listeners.get(event.type) || []) fn(event);
    return true;
  }
  click() {
    this.dispatchEvent({ type: "click", target: this, preventDefault() {}, stopPropagation() {} });
  }
  focus() {
    setActiveElement(this);
    this.dispatchEvent({ type: "focus", target: this });
  }
  blur() {
    if (getActiveElement() === this) setActiveElement(null);
    this.dispatchEvent({ type: "blur", target: this });
  }

  querySelector(sel) {
    return queryAll(this, sel)[0] || null;
  }
  querySelectorAll(sel) {
    return queryAll(this, sel);
  }
  closest(sel) {
    let cur = this;
    while (cur) {
      if (matchesSimpleSelector(cur, sel)) return cur;
      cur = cur.parentNode;
    }
    return null;
  }
  contains(other) {
    let cur = other;
    while (cur) {
      if (cur === this) return true;
      cur = cur.parentNode;
    }
    return false;
  }

  get clientWidth() {
    return this._clientWidth ?? 800;
  }
  set clientWidth(v) {
    this._clientWidth = v;
  }
  get clientHeight() {
    return this._clientHeight ?? 600;
  }
  set clientHeight(v) {
    this._clientHeight = v;
  }
  getBoundingClientRect() {
    return { top: 0, left: 0, right: this.clientWidth, bottom: this.clientHeight, width: this.clientWidth, height: this.clientHeight };
  }
  get options() {
    if (this.tagName !== "SELECT") return undefined;
    return this.children.filter((c) => c.tagName === "OPTION");
  }
  get selectedIndex() {
    if (this.tagName !== "SELECT") return -1;
    const opts = this.options;
    const idx = opts.findIndex((o) => o._selected);
    return idx === -1 ? (opts.length ? 0 : -1) : idx;
  }
  set selectedIndex(i) {
    if (this.tagName !== "SELECT") return;
    const opts = this.options;
    opts.forEach((o, idx) => (o._selected = idx === i));
    if (opts[i]) this._value = opts[i].value;
  }

  get value() {
    if (this.tagName === "SELECT") {
      const opts = this.options;
      const sel = opts.find((o) => o._selected);
      return sel ? sel.value : (opts[0] ? opts[0].value : "");
    }
    if (this.tagName === "OPTION") {
      return this.hasAttribute("value") ? this.getAttribute("value") : this.textContent;
    }
    return this._value ?? "";
  }
  set value(v) {
    if (this.tagName === "SELECT") {
      const opts = this.options;
      opts.forEach((o) => (o._selected = o.value === String(v)));
      this._value = v;
      return;
    }
    this._value = v;
  }

  get selected() {
    return !!this._selected;
  }
  set selected(v) {
    this._selected = !!v;
  }

  get text() {
    if (this.tagName === "OPTION") return this.textContent;
    return undefined;
  }
  set text(v) {
    if (this.tagName === "OPTION") this.textContent = v;
  }

  scrollIntoView() {}
  getContext() {
    return null; // no real WebGL in the offline shim; override per-test if needed
  }
}

class LocalStorage {
  constructor() {
    this._data = new Map();
  }
  getItem(key) {
    return this._data.has(key) ? this._data.get(key) : null;
  }
  setItem(key, value) {
    this._data.set(key, String(value));
  }
  removeItem(key) {
    this._data.delete(key);
  }
  clear() {
    this._data.clear();
  }
  key(i) {
    return [...this._data.keys()][i] ?? null;
  }
  get length() {
    return this._data.size;
  }
}

export function installMinimalDOM() {
  _activeElement = null;
  const documentRoot = new Element("html");
  const body = new Element("body");
  const head = new Element("head");
  documentRoot.appendChild(head);
  documentRoot.appendChild(body);

  const byId = new Map();

  const doc = {
    documentElement: documentRoot,
    body,
    head,
    createElement(tag) {
      return new Element(tag);
    },
    createTextNode(text) {
      const el = new Element("#text");
      el._text = String(text);
      return el;
    },
    createDocumentFragment() {
      return new Element("#fragment");
    },
    getElementById(id) {
      return queryAll(documentRoot, `#${id}`)[0] || null;
    },
    querySelector(sel) {
      return queryAll(documentRoot, sel)[0] || null;
    },
    querySelectorAll(sel) {
      return queryAll(documentRoot, sel);
    },
    addEventListener: Element.prototype.addEventListener.bind(documentRoot),
    removeEventListener: Element.prototype.removeEventListener.bind(documentRoot),
    dispatchEvent: Element.prototype.dispatchEvent.bind(documentRoot),
    get activeElement() {
      return _activeElement || body;
    },
    _listeners: new Map(),
    visibilityState: "visible",
    hidden: false,
  };
  // documentRoot needs its own listener map separate from `doc`'s helper bind above
  doc.addEventListener = (type, fn) => documentRoot.addEventListener(type, fn);
  doc.removeEventListener = (type, fn) => documentRoot.removeEventListener(type, fn);
  doc.dispatchEvent = (ev) => documentRoot.dispatchEvent(ev);

  const win = {
    document: doc,
    innerWidth: 1280,
    innerHeight: 800,
    devicePixelRatio: 1,
    location: { protocol: "http:", href: "http://localhost/", search: "", hostname: "localhost" },
    navigator: globalThis.navigator,
    localStorage: new LocalStorage(),
    sessionStorage: new LocalStorage(),
    requestAnimationFrame(fn) {
      return setTimeout(() => fn(Date.now()), 0);
    },
    cancelAnimationFrame(id) {
      clearTimeout(id);
    },
    matchMedia() {
      return { matches: false, addEventListener() {}, removeEventListener() {} };
    },
    getComputedStyle(el) {
      return el.style || {};
    },
    addEventListener: Element.prototype.addEventListener.bind(documentRoot),
    removeEventListener: Element.prototype.removeEventListener.bind(documentRoot),
    dispatchEvent: Element.prototype.dispatchEvent.bind(documentRoot),
    CustomEvent: class CustomEvent {
      constructor(type, opts = {}) {
        this.type = type;
        this.detail = opts.detail;
      }
    },
    ResizeObserver: class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  };
  win.addEventListener = (type, fn) => documentRoot.addEventListener(type, fn);
  win.removeEventListener = (type, fn) => documentRoot.removeEventListener(type, fn);

  global.window = win;
  global.document = doc;
  global.localStorage = win.localStorage;
  global.sessionStorage = win.sessionStorage;
  global.ResizeObserver = win.ResizeObserver;
  global.CustomEvent = win.CustomEvent;
  global.Event = class Event {
    constructor(type, opts = {}) {
      this.type = type;
      this.bubbles = !!opts.bubbles;
      this.cancelable = !!opts.cancelable;
      this.defaultPrevented = false;
    }
    preventDefault() {
      this.defaultPrevented = true;
    }
    stopPropagation() {}
  };
  global.requestAnimationFrame = win.requestAnimationFrame;
  global.cancelAnimationFrame = win.cancelAnimationFrame;
  global.HTMLElement = Element;

  return { window: win, document: doc };
}

export { Element };
