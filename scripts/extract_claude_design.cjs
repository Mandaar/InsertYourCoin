// Extraction fidele du design Claude Design (InsertYourCoin_v3.dc.html)
//
// Ce script NE RECONSTRUIT RIEN : il isole le template (x-dc) et le script de
// donnees (data-dc-script), EXECUTE ce script en Node (le vrai JS source,
// const THEMES / VERDICTS / class Component.renderVals()), puis resout les
// {{ expr }}, <sc-if>, <sc-for> du template avec les valeurs REELLEMENT
// calculees. Sortie : un fichier HTML autonome par ecran x etat x theme dans
// docs/design/from_claude_design/rendered/.
//
// Usage : node scripts/extract_claude_design.cjs

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SRC = path.join(ROOT, 'docs', 'design', 'from_claude_design', 'InsertYourCoin_v3.dc.html');
const OUT_DIR = path.join(ROOT, 'docs', 'design', 'from_claude_design', 'rendered');
const GEN_PATH = path.join(__dirname, '_generated_component.cjs');

const html = fs.readFileSync(SRC, 'utf8');

// ---------------------------------------------------------------------------
// 1. Extraire le <style> du <helmet> (CSS globale : liens, focus-visible, keyframes)
// ---------------------------------------------------------------------------
const helmetMatch = html.match(/<helmet>\s*<style>([\s\S]*?)<\/style>\s*<\/helmet>/);
if (!helmetMatch) throw new Error('helmet <style> introuvable');
const helmetStyle = helmetMatch[1];

// ---------------------------------------------------------------------------
// 2. Extraire le script de donnees (data-dc-script) + son data-props
// ---------------------------------------------------------------------------
const scriptTagMatch = html.match(/<script type="text\/x-dc" data-dc-script data-props="([^"]*)">/);
if (!scriptTagMatch) throw new Error('balise <script data-dc-script> introuvable');
const dataPropsRaw = scriptTagMatch[1];
const dataPropsJson = dataPropsRaw
  .replace(/&quot;/g, '"')
  .replace(/&lt;/g, '<')
  .replace(/&gt;/g, '>')
  .replace(/&amp;/g, '&');
const propsSpec = JSON.parse(dataPropsJson);
const defaultProps = {};
for (const [k, v] of Object.entries(propsSpec)) defaultProps[k] = v.default;

const scriptStart = scriptTagMatch.index + scriptTagMatch[0].length;
const scriptEnd = html.indexOf('</script>', scriptStart);
if (scriptEnd === -1) throw new Error('fermeture </script> introuvable');
const scriptSrc = html.slice(scriptStart, scriptEnd);

// ---------------------------------------------------------------------------
// 3. Ecrire + charger un module CommonJS contenant le VRAI JS source (execute,
//    pas recopie a la main). DCLogic est le seul stub necessaire (base class
//    du runtime Claude Design ; ici juste state + setState).
// ---------------------------------------------------------------------------
const moduleSrc = [
  '"use strict";',
  'class DCLogic {',
  '  constructor(){ this.state = {}; this.props = {}; }',
  '  setState(patch){ Object.assign(this.state, patch); }',
  '}',
  scriptSrc,
  'module.exports = { Component, THEMES, VERDICTS, TABS };',
].join('\n');
fs.writeFileSync(GEN_PATH, moduleSrc, 'utf8');
delete require.cache[require.resolve(GEN_PATH)];
const { Component, THEMES, VERDICTS, TABS } = require(GEN_PATH);

// ---------------------------------------------------------------------------
// 4. Parseur XML/HTML minimal (recursif, suffisant pour ce template bien forme)
// ---------------------------------------------------------------------------
function parseTemplate(str, startIdx) {
  let i = startIdx;

  function skipWs() {
    while (i < str.length && /\s/.test(str[i])) i++;
  }

  function parseElement() {
    // str[i] === '<'
    i++; // consomme '<'
    const nameStart = i;
    while (/[a-zA-Z0-9\-]/.test(str[i])) i++;
    const tag = str.slice(nameStart, i);
    const attrs = {};
    const attrOrder = [];
    for (;;) {
      skipWs();
      if (str.startsWith('/>', i)) {
        i += 2;
        return { type: 'element', tag, attrs, attrOrder, children: [] };
      }
      if (str[i] === '>') {
        i++;
        break;
      }
      const anStart = i;
      while (i < str.length && !/[\s=\/>]/.test(str[i])) i++;
      const aname = str.slice(anStart, i);
      if (!aname) { i++; continue; }
      skipWs();
      let aval = '';
      if (str[i] === '=') {
        i++;
        skipWs();
        const q = str[i];
        i++;
        const vs = i;
        while (i < str.length && str[i] !== q) i++;
        aval = str.slice(vs, i);
        i++; // consomme la quote fermante
      }
      attrs[aname] = aval;
      attrOrder.push(aname);
    }
    const children = [];
    for (;;) {
      if (i >= str.length) break;
      if (str.startsWith('</', i)) {
        i += 2;
        while (i < str.length && str[i] !== '>') i++;
        i++; // consomme '>'
        break;
      }
      if (str[i] === '<') {
        children.push(parseElement());
      } else {
        const ts = i;
        while (i < str.length && str[i] !== '<') i++;
        children.push({ type: 'text', value: str.slice(ts, i) });
      }
    }
    return { type: 'element', tag, attrs, attrOrder, children };
  }

  const node = parseElement();
  return node;
}

const ROOT_MARKER = '<div style="{{ rootStyle }}">';
const rootIdx = html.indexOf(ROOT_MARKER);
if (rootIdx === -1) throw new Error('racine du template introuvable');
const templateAst = parseTemplate(html, rootIdx);

// ---------------------------------------------------------------------------
// 5. Moteur de resolution : {{ expr }}, sc-if, sc-for -> HTML final
// ---------------------------------------------------------------------------
function evalExpr(expr, ctx) {
  const fn = new Function('ctx', 'with (ctx) { return (' + expr + '); }');
  return fn(ctx);
}

function kebab(k) {
  return k.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase());
}

function styleObjToCss(obj) {
  return Object.entries(obj)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => kebab(k) + ':' + v)
    .join(';');
}

function escapeAttr(s) {
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

const FULL_MUSTACHE = /^\{\{([\s\S]*)\}\}$/;

function resolveAttrValue(raw, ctx) {
  const m = raw.match(FULL_MUSTACHE);
  if (m) {
    const val = evalExpr(m[1].trim(), ctx);
    if (val === null || val === undefined || typeof val === 'function') return '';
    if (typeof val === 'object') return styleObjToCss(val);
    return String(val);
  }
  return raw.replace(/\{\{([\s\S]*?)\}\}/g, (_, e) => {
    const val = evalExpr(e.trim(), ctx);
    return val === null || val === undefined ? '' : String(val);
  });
}

function resolveText(raw, ctx) {
  return raw.replace(/\{\{([\s\S]*?)\}\}/g, (_, e) => {
    const val = evalExpr(e.trim(), ctx);
    return val === null || val === undefined ? '' : String(val);
  });
}

const VOID_TAGS = new Set(['input', 'br', 'hr', 'img', 'meta', 'link']);

function renderNode(node, ctx, out) {
  if (node.type === 'text') {
    out.push(resolveText(node.value, ctx));
    return;
  }
  const { tag, attrs, attrOrder, children } = node;

  if (tag === 'sc-if') {
    const m = attrs.value.match(FULL_MUSTACHE);
    const val = evalExpr(m[1].trim(), ctx);
    if (val) children.forEach((c) => renderNode(c, ctx, out));
    return;
  }
  if (tag === 'sc-for') {
    const m = attrs.list.match(FULL_MUSTACHE);
    const list = evalExpr(m[1].trim(), ctx) || [];
    const asName = attrs.as;
    list.forEach((item) => {
      const childCtx = Object.assign({}, ctx, { [asName]: item });
      children.forEach((c) => renderNode(c, childCtx, out));
    });
    return;
  }

  out.push('<' + tag);
  for (const k of attrOrder) {
    if (k === 'onClick') continue; // rendu statique : pas d'interactivite JS
    if (k.startsWith('hint-placeholder')) continue; // artefact de l'outil de design
    const resolved = resolveAttrValue(attrs[k], ctx);
    out.push(' ' + k + '="' + escapeAttr(resolved) + '"');
  }
  if (children.length === 0 && VOID_TAGS.has(tag)) {
    out.push(' />');
    return;
  }
  out.push('>');
  children.forEach((c) => renderNode(c, ctx, out));
  out.push('</' + tag + '>');
}

function wrapHtml(bodyHtml, title) {
  return [
    '<!DOCTYPE html>',
    '<html lang="fr">',
    '<head>',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<title>' + title + '</title>',
    '<style>' + helmetStyle + '</style>',
    '</head>',
    '<body>',
    bodyHtml,
    '</body>',
    '</html>',
  ].join('\n');
}

// ---------------------------------------------------------------------------
// 6. Matrice ecrans x etats x themes
// ---------------------------------------------------------------------------
const THEME_IDS = ['violet', 'dark', 'light'];

const COMBOS = [
  { label: 'accueil_etat-ok', state: { screen: 'accueil', acc: 'ok' } },
  { label: 'accueil_etat-ssl-echec', state: { screen: 'accueil', acc: 'ssl' } },
  { label: 'accueil_etat-rien-ne-tourne', state: { screen: 'accueil', acc: 'rien' } },
  { label: 'monitoring_direct', state: { screen: 'monitoring', mon: 'direct' } },
  { label: 'monitoring_inactif-360s', state: { screen: 'monitoring', mon: 'inactif' } },
  { label: 'monitoring_vide-jamais-lance', state: { screen: 'monitoring', mon: 'vide' } },
  { label: 'walkforward_calcul-en-cours', state: { screen: 'wf', wfPhase: 'running' } },
  { label: 'walkforward_verdict-rouge', state: { screen: 'wf', wfPhase: 'done', verdict: 'rouge' } },
  { label: 'walkforward_verdict-ambre', state: { screen: 'wf', wfPhase: 'done', verdict: 'ambre' } },
  { label: 'walkforward_verdict-vert', state: { screen: 'wf', wfPhase: 'done', verdict: 'vert' } },
  { label: 'stats_labo', state: { screen: 'stats' } },
  { label: 'diagnostic_ok', state: { screen: 'check', acc: 'ok' } },
  { label: 'diagnostic_ssl-echec', state: { screen: 'check', acc: 'ssl' } },
  { label: 'paper_en-cours', state: { screen: 'paper' } },
  { label: 'options', state: { screen: 'options' } },
  { label: 'aide', state: { screen: 'help' } },
];

fs.mkdirSync(OUT_DIR, { recursive: true });
// nettoie les anciens rendus (le dossier n'est que du materiel de reference regenerable)
for (const f of fs.readdirSync(OUT_DIR)) {
  if (f.endsWith('.html')) fs.unlinkSync(path.join(OUT_DIR, f));
}

const manifest = [];
for (const themeId of THEME_IDS) {
  for (const combo of COMBOS) {
    const inst = new Component();
    inst.props = defaultProps;
    inst.state = Object.assign({}, inst.state, combo.state, { theme: themeId });
    const vals = inst.renderVals();
    const out = [];
    renderNode(templateAst, vals, out);
    const bodyHtml = out.join('');
    const fname = combo.label + '__theme-' + themeId + '.html';
    const title = 'InsertYourCoin - ' + combo.label + ' (' + themeId + ')';
    fs.writeFileSync(path.join(OUT_DIR, fname), wrapHtml(bodyHtml, title), 'utf8');
    manifest.push({ file: fname, screen: combo.state.screen, etat: combo.label, theme: themeId });
  }
}

fs.writeFileSync(
  path.join(OUT_DIR, '_MANIFEST.json'),
  JSON.stringify({ generated: new Date().toISOString(), count: manifest.length, items: manifest }, null, 2),
  'utf8'
);

console.log('OK — ' + manifest.length + ' rendus ecrits dans ' + OUT_DIR);
console.log('Themes exposes (cles CSS) : ' + Object.keys(THEMES).join(', '));
console.log('Verdicts exposes : ' + Object.keys(VERDICTS).join(', '));
console.log('Onglets (TABS) : ' + TABS.map((t) => t[1]).join(', '));
