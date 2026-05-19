#!/usr/bin/env node


const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const CHARACTERS_DIR = path.join(PROJECT_ROOT, 'characters');
const RENDERER_URL = 'http:
const DEFAULT_VRM = '/characters/default/model.vrm';
const ICON_SIZE = 96;
const regenerateAll = process.argv.includes('--all');

async function main() {
    
    const chromePath = '/usr/bin/google-chrome';
    if (!fs.existsSync(chromePath)) {
        console.error(`Chrome not found at ${chromePath}. Install google-chrome or chromium.`);
        console.error('  Ubuntu/Debian: sudo apt install google-chrome-stable');
        console.error('  Or set executablePath in this script to your chromium path.');
        process.exit(1);
    }

    
    try {
        await fetch('http:
    } catch {
        console.error('Backend not running on localhost:8000. Start it first with: python -m backend');
        process.exit(1);
    }

    let browser;
    try {
        browser = await puppeteer.launch({
            executablePath: chromePath,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--enable-webgl', '--use-gl=egl', '--enable-unsafe-swiftshader'],
        });
    } catch (err) {
        console.error(`Failed to launch Chrome: ${err.message}`);
        console.error('Make sure Chrome/Chromium is installed and can run headless.');
        process.exit(1);
    }

    const page = await browser.newPage();
    try {
        
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

                
                await page.evaluate(() => { window.__vrmError = false; window.__vrmReady = false; });

                
                await page.waitForFunction('window.__vrmReady === true', { timeout: 180000 });

                
                const hadError = await page.evaluate(() => window.__vrmError === true);
                if (hadError) {
                    console.warn(`  ${label}: VRM load failed, skipping`);
                    continue;
                }

                
                await new Promise(r => setTimeout(r, 1000));

                
                const tmpPath = iconPath + '.tmp.png';
                await page.screenshot({ path: tmpPath, type: 'png' });

                
                const tmpSize = fs.statSync(tmpPath).size;
                if (tmpSize < 3000) {
                    fs.unlinkSync(tmpPath);
                    console.warn(`  ${label}: screenshot too small (${tmpSize}B), likely blank — skipping`);
                    continue;
                }

                
                const { execSync } = require('child_process');
                execSync(`convert "${tmpPath}" -gravity center -extent 90%x90% -resize ${ICON_SIZE}x${ICON_SIZE}! -quality 95 "${iconPath}"`);
                fs.unlinkSync(tmpPath);

                
                const iconSize = fs.statSync(iconPath).size;
                if (iconSize < 3000) {
                    console.warn(`  ${label}: icon too small (${iconSize}B), likely failed render — deleting`);
                    fs.unlinkSync(iconPath);
                    continue;
                }

                console.log(`  ${label}: generated (${(iconSize / 1024).toFixed(1)}KB)`);
                generated++;
            } catch (err) {
                console.warn(`  ${label}: error - ${err.message}`);
            }
        }

        console.log(`\nDone: ${generated} generated, ${skipped} skipped`);
    } finally {
        await browser.close();
    }
}

main().catch(err => {
    console.error('Fatal:', err);
    process.exit(1);
});
