const Potrace = require('../node_modules/potrace/lib/Potrace');
const fs = require('fs');
const path = require('path');

const input = path.join(__dirname, '..', 'static', 'img', 'logo.png');
const output = path.join(__dirname, '..', 'static', 'img', 'logo_traced.svg');

const potrace = new Potrace();

potrace.loadImage(input, function(err) {
  if (err) return console.error('loadImage error', err);
  potrace.setParameters({ turdSize: 100, turnPolicy: Potrace.TURNPOLICY_MINORITY });
  try {
    const svg = potrace.getSVG();
    fs.writeFileSync(output, svg, 'utf8');
    console.log('SVG written to', output);
  } catch (e) {
    console.error('tracing error', e);
  }
});
