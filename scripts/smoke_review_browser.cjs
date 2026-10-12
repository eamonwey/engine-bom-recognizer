// Existing bundled Playwright fallback when Python package installation fails.
const {chromium}=require('playwright');
const fs=require('fs'), path=require('path');
const out=path.resolve(__dirname,'../data/reports/validation/browser_checks');
fs.mkdirSync(out,{recursive:true});
function check(value,message){if(!value)throw Error(message);}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 try{
 const page=await browser.newPage({viewport:{width:1360,height:900},acceptDownloads:true});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto('http://127.0.0.1:8788/static/validation/index.html');await page.waitForLoadState('networkidle');
 check(await page.locator('.case').count()===30,'external count');
 check(await page.locator('#title').innerText()==='enginuity_01','first case');
 check(await page.locator('#reference-card').isHidden(),'reference hidden');
 check(await page.locator('#prediction-card').isHidden(),'prediction hidden');
 check(await page.locator('#pages img').count()===2,'source images');
 await page.locator('#reference').click();check(await page.locator('#independent').isDisabled(),'exposure gate');
 await page.locator('#prediction').click();check((await page.locator('#prediction-json').innerText()).includes('qwen37_max_reference_v1'),'model data');
 await page.screenshot({path:path.join(out,'review_desktop.png'),fullPage:true});
 await page.locator('#filter').selectOption('synthetic');check(await page.locator('.case').count()===40,'synthetic count');
 await page.locator('#reviewer').fill('AUTOMATED_UI_TEST_NOT_A_HUMAN_APPROVAL');
 await page.locator('#components').fill(JSON.stringify([{part_number:'TEST',quantity:null,source_page:1}]));
 await page.locator('#save').click();check((await page.locator('#message').innerText()).includes('已记录'),'save');
 const download=page.waitForEvent('download');await page.locator('#export').click();
 const data=JSON.parse(fs.readFileSync(await (await download).path(),'utf8'));
 check(data.reviews.length===1&&data.reviews[0].status==='needs_review'&&!data.reviews[0].independent&&data.reviews[0].synthetic,'no approval');
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'review_mobile.png'),fullPage:true});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile overflow');
 await page.screenshot({path:path.join(out,'review_mobile_viewport.png')});
 await page.goto('http://127.0.0.1:8788/');await page.waitForLoadState('networkidle');
 check((await page.locator('body').innerText()).includes('BOM 与图纸纠错'),'combined entry');
 await page.locator('#bom-provider').selectOption('mock');
 await page.locator('#bom-file').setInputFiles(path.resolve(__dirname,'../data/validation/synthetic/inputs/synthetic_01_clean.pdf'));
 await page.locator('#bom-start').click();
 await page.locator('#bom-result').waitFor({state:'visible',timeout:30000});
 await page.waitForFunction(()=>document.querySelector('#ins-preview').width>300&&document.querySelector('#ins-preview').height>150);
 check(await page.locator('#bom-table tr').count()>1,'BOM rows');
 check(await page.locator('#bom-issues').isVisible(),'combined issues');
 check(await page.locator('#ins-correct').isVisible(),'same-page correction');
 check(await page.locator('#bom-error').isHidden(),'no upload error');
 await page.screenshot({path:path.join(out,'combined_mobile_mock.png'),fullPage:true});
 check(errors.length===0,errors.join('\n'));
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'passed',checks:['30/40 case switching','source images','hidden labels','exposure gate','model results','unapproved synthetic save/export','mobile layout','combined entry','mock UI upload/BOM/issues/correction controls','no page errors'],human_approvals_created:0},null,2));
 console.log('PASS: headless review UI; zero human approvals created');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

