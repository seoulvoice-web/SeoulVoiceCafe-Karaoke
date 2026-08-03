const fs = require('fs');
const { createCanvas, loadImage } = require('canvas');
const ImageTracer = require('imagetracerjs');

const input = 'static/img/logo.png';
const output = 'static/img/logo_color.svg';

const options = {
  numberofcolors: 32,
  mincolorratio: 0,
  colorquantcycles: 3,
  scale: 1,
  strokewidth: 1
};

console.log('Loading', input);
loadImage(input).then(img => {
  const canvas = createCanvas(img.width, img.height);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);
  const imageData = ctx.getImageData(0, 0, img.width, img.height);
  const svgstr = ImageTracer.imagedataToSVG(imageData, options);
  fs.writeFileSync(output, svgstr, 'utf8');
  console.log('SVG written to', output);
}).catch(err => {
  console.error('Failed to load image:', err);
  process.exit(1);
});
