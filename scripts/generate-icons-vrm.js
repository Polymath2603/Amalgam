#!/usr/bin/env node


const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const CHARACTERS_DIR = path.join(PROJECT_ROOT, 'characters');
const RENDERER_URL = 'http:
const DEFAULT_VRM = '/user_data/avatars/avatar.vrm';
const ICON_SIZE = 96;
const regenerateAll = process.argv.includes('--all');

async function main() {
    
    try {
        await fetch('http:
    } catch {
        console.error('Backend not running on localhost:8000. Start it first with: python -m backend');
        process.exit(1);
    }

    const browser = await puppeteer.launch({
        executablePath: '/usr/bin/google-chrome',
        headless: 'new',
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--enable-webgl', '--use-gl=egl', '--enable-unsafe-swiftshader'],
    });

    const page = await browser.newPage();
    
    await page.setViewport({ width: 192, height: 192, deviceScaleFactor: 2 });

    
    const chars = fs.readdirSync(CHARACTERS_DIR)
        .filter(d => fs.statSync(path.join(CHARACTERS_DIR, d)).isDirectory())
        .sort();

    let generated = 0;
    let skipped = 0;

    for (const charDir of chars) {
        const iconPath = path.join(CHARACTERS_DIR, charDir, 'icon.png');

        if (!regenerateAll && fs.existsSync(iconPath)) {
            skipped++;
            continue;
        }

        
        const charModelPath = path.join(CHARACTERS_DIR, charDir, 'model.vrm');
        const hasCharModel = fs.existsSync(charModelPath);
        const vrmUrl = hasCharModel
            ? `/characters/${charDir}/model.vrm`
            : DEFAULT_VRM;

        const url = `${RENDERER_URL}?model=${encodeURIComponent(vrmUrl)}`;
        const label = hasCharModel ? `${charDir} (custom VRM)` : `${charDir} (default VRM)`;

        try {
            await page.goto(url, { waitUntil: 'networkidle0', timeout: 180000 });

            
            await page.waitForFunction('window.__vrmReady === true', { timeout: 180000 });

            
            await new Promise(r => setTimeout(r, 1000));

            
            const tmpPath = iconPath + '.tmp.png';
            await page.screenshot({ path: tmpPath, type: 'png' });

            
            const { execSync } = require('child_process');
            execSync(`convert "${tmpPath}" -gravity center -extent 90%x90% -resize ${ICON_SIZE}x${ICON_SIZE} -quality 95 "${iconPath}"`);
            fs.unlinkSync(tmpPath);

            console.log(`  ${label}: generated`);
            generated++;
        } catch (err) {
            console.warn(`  ${label}: error - ${err.message}`);
        }
    }

    await browser.close();
    console.log(`\nDone: ${generated} generated, ${skipped} skipped`);
}

main().catch(err => {
    console.error('Fatal:', err);
    process.exit(1);
});
