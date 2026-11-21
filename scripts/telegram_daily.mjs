// Resumo diário no Telegram: abre o painel gerado em modo cartão, tira a foto
// do cartão e envia com legenda e botões. Uso: node scripts/telegram_daily.mjs [--dry]
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';

const dry = process.argv.includes('--dry');
const token = process.env.TELEGRAM_BOT_TOKEN;
const chat = process.env.TELEGRAM_CHAT_ID;
const site = process.env.SITE_URL || 'https://garmin-performance.vercel.app/performance.html';
const page = path.resolve(process.env.PERFORMANCE_HTML || 'output/performance.html');

if (!dry && (!token || !chat)) {
  console.log('Telegram não configurado (faltam TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID). Pulando.');
  process.exit(0);
}
if (!fs.existsSync(page)) {
  console.error('performance.html não encontrado:', page);
  process.exit(1);
}

const exe = process.env.CHROME_PATH ||
  ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium-browser', '/usr/bin/chromium']
    .find((p) => fs.existsSync(p));

const browser = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
const ctx = await browser.newContext({
  viewport: { width: 540, height: 1000 },
  deviceScaleFactor: 2,
  timezoneId: 'America/Sao_Paulo',
  locale: 'pt-BR',
  reducedMotion: 'reduce',
});
const tab = await ctx.newPage();
const errors = [];
tab.on('pageerror', (e) => errors.push(e.message));
await tab.goto('file://' + page + '#card');
await tab.waitForFunction(() => window.TG, null, { timeout: 20000 });
await tab.waitForTimeout(400);
const tg = await tab.evaluate(() => window.TG);
const png = await (await tab.$('#tgcard')).screenshot({ type: 'png' });
await browser.close();
if (errors.length) console.log('Avisos da página:', errors.slice(0, 3).join(' | '));

if (dry) {
  fs.writeFileSync('output/telegram_card.png', png);
  fs.writeFileSync('output/telegram_caption.txt', tg.caption);
  console.log(tg.caption);
  console.log('\n(modo de teste: nada enviado)');
  process.exit(0);
}

const keyboard = {
  inline_keyboard: [[
    { text: '📲 Abrir o painel', url: site + '#hoje' },
    { text: '🏃 Último treino', url: site + '#ultimo' },
  ]],
};
const api = (m) => `https://api.telegram.org/bot${token}/${m}`;

const fd = new FormData();
fd.append('chat_id', chat);
fd.append('caption', tg.caption);
fd.append('parse_mode', 'HTML');
fd.append('reply_markup', JSON.stringify(keyboard));
fd.append('photo', new Blob([png], { type: 'image/png' }), 'hoje.png');
let res = await (await fetch(api('sendPhoto'), { method: 'POST', body: fd })).json();

if (!res.ok) {
  console.log('Foto não enviada (' + res.description + '). Tentando só o texto.');
  res = await (await fetch(api('sendMessage'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ chat_id: chat, text: tg.caption, parse_mode: 'HTML', reply_markup: keyboard }),
  })).json();
}
if (!res.ok) {
  console.error('Telegram recusou o envio: ' + res.description);
  process.exit(1);
}
console.log('Resumo enviado ao Telegram (prontidão ' + tg.score + ').');
