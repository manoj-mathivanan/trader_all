'use strict';
let researchArchiveData = null;
let researchArchiveLoading = false;
let researchArchiveError = false;

function researchArchiveView(category){
  const title=category==='intraday'?'Intraday':'Futures';
  const introduction=category==='intraday'
    ? 'Opening-range momentum, scalping, stock selection, cost studies, candle setups and four-indicator intraday experiments.'
    : 'Derivatives research archive. Our completed investigations tested options; a separate profitable futures strategy has not been established.';
  const status=heading(title,'No positive automation found','','RESEARCH ARCHIVE / '+title.toUpperCase())+
    `<section class="panel"><div class="panel-body"><span class="badge">Research only · not validated</span><h2>No positive automation found</h2><p>${introduction}</p><p>Some individual trials were positive. None established a reliable automation after costs, later-period comparison and sufficient observations. The findings below preserve those results and their limitations.</p>${category==='futures'?'<p>The options profit-protection variant was frozen for forward paper observation. That is evidence collection, not a validated profitable automation. Historical setup snapshots below are dated records; current cycle status is in Jobs &amp; logs.</p>':''}</div></section>`;
  if(!researchArchiveData){
    if(!researchArchiveLoading&&!researchArchiveError){
      researchArchiveLoading=true;
      fetch('/static/research-archive-data.json').then(response=>{if(!response.ok)throw Error('Archive unavailable');return response.json();}).then(data=>{
        researchArchiveData=data;researchArchiveLoading=false;
        if(['intraday','futures'].includes(currentView))render();
      }).catch(()=>{researchArchiveLoading=false;researchArchiveError=true;if(['intraday','futures'].includes(currentView))render();});
    }
    return status+`<div class="notice" role="status">${researchArchiveError?'The saved analysis could not be loaded. Reload this page to retry.':'Loading saved analysis…'}</div>`;
  }
  const records=researchArchiveData.records.filter(record=>record.category===category);
  const groups=[['Saved reports and studies',records.filter(record=>!record.source.startsWith('Chat:'))],['Earlier chat findings',records.filter(record=>record.source.startsWith('Chat:'))]];
  return status+`<section class="panel research-archive"><div class="panel-head"><div><h2>Analysis archive</h2><p>${records.length} retained findings and reports · snapshot ${esc(researchArchiveData.as_of)}</p></div><a class="button" href="/static/research-archive-data.json" download="trading-research-archive.json">Download all analysis</a></div><div class="panel-body"><p>Expand a record to read its complete saved analysis. Original assumptions and dated conclusions are retained; older cost models and proposed next steps describe their original experiments.</p>${groups.map(([label,items])=>`<h3>${label}</h3>${items.map(record=>`<details class="research-record"><summary>${esc(record.title)}</summary><p class="research-source">Source: ${esc(record.source)}</p><pre class="research-content">${esc(record.content)}</pre></details>`).join('')}`).join('')}</div></section>`;
}
