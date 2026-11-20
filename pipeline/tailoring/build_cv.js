// Build a CV .docx from a JSON file, in a plain two-page ATS-friendly layout:
// Name, contact line, PROFESSIONAL SUMMARY, EDUCATION, TECHNICAL SKILLS, WORK EXPERIENCE, CERTIFICATIONS.
// Usage: node build_cv.js input.json output.docx
const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, AlignmentType, TabStopType, BorderStyle, LevelFormat } = require('docx');

const cv = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const FONT = 'Calibri';
const PAGE_W = 11906, MARGIN = 850; // A4, ~1.5 cm margins
const RIGHT = PAGE_W - 2 * MARGIN;

const heading = (t) => new Paragraph({
  spacing: { before: 200, after: 80 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: '1F3A68', space: 2 } },
  children: [new TextRun({ text: t.toUpperCase(), bold: true, size: 22, color: '1F3A68', font: FONT })],
});
const body = (runs, opts = {}) => new Paragraph({ spacing: { after: 60 }, ...opts, children: runs });
const t = (text, o = {}) => new TextRun({ text, size: 20, font: FONT, ...o });

const kids = [];
kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: cv.name, bold: true, size: 36, font: FONT, color: '17202E' })] }));
kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 },
  children: [t(cv.contact.join('  |  '), { size: 19 })] }));

const sections = {
  summary: () => { kids.push(heading('Professional Summary')); kids.push(body([t(cv.summary)], { alignment: AlignmentType.JUSTIFIED })); },
  education: () => {
    kids.push(heading('Education'));
    for (const e of cv.education) {
      kids.push(body([t(e.title, { bold: true }), t(e.dates ? `\t${e.dates}` : '')], { tabStops: [{ type: TabStopType.RIGHT, position: RIGHT }] }));
      kids.push(body([t(e.org)]));
    }
  },
  skills: () => { kids.push(heading('Technical Skills')); for (const [k, v] of cv.skills) kids.push(body([t(`${k}: `, { bold: true }), t(v)])); },
  experience: () => {
    kids.push(heading('Work Experience'));
    for (const job of cv.experience) {
      kids.push(new Paragraph({ keepNext: true, keepLines: true, spacing: { before: 120, after: 0 }, tabStops: [{ type: TabStopType.RIGHT, position: RIGHT }],
        children: [t(job.title, { bold: true }), t(`\t${job.dates}`, { bold: true })] }));
      kids.push(new Paragraph({ keepNext: true, spacing: { after: 40 }, children: [t(job.location ? `${job.org} | ${job.location}` : job.org, { italics: true })] }));
      for (const b of job.bullets) kids.push(new Paragraph({ numbering: { reference: 'bul', level: 0 }, spacing: { after: 40 }, alignment: AlignmentType.JUSTIFIED, children: [t(b)] }));
    }
  },
  certifications: () => {
    if (!cv.certifications || !cv.certifications.length) return;
    kids.push(heading('Certifications'));
    for (const c of cv.certifications) kids.push(new Paragraph({ numbering: { reference: 'bul', level: 0 }, spacing: { after: 30 }, children: [t(c)] }));
  },
};
// Default section order; a CV JSON can override with section_order.
for (const k of (cv.section_order || ['summary', 'education', 'skills', 'experience', 'certifications'])) sections[k]();

const doc = new Document({
  creator: cv.name, title: `${cv.name} CV`,
  numbering: { config: [{ reference: 'bul', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] }] },
  sections: [{ properties: { page: { size: { width: PAGE_W, height: 16838 },
    margin: { top: 720, bottom: 720, left: MARGIN, right: MARGIN } } }, children: kids }],
});
Packer.toBuffer(doc).then((buf) => fs.writeFileSync(process.argv[3], buf));
