'use strict';
let accountSession=null,adminData=null,accountGeneration=0;
const isAdmin=()=>Boolean(state?.user?.is_admin);
function clearAccountState(){
  accountGeneration++;state=null;accountSession=null;adminData=null;
  if(typeof companyState!=='undefined'){companyState=null;companyUniverse=null;companyScan=null;companySelectedReview=null;}
  if(typeof liveState!=='undefined'){liveState=null;liveHistory=null;livePlan=null;liveError='';}
  if(typeof investorState!=='undefined')investorState=null;
  if($('#modal')?.open)$('#modal').close();
}
function accountHeader(){
  let tools=$('#account-tools');
  if(!tools){tools=document.createElement('span');tools.id='account-tools';tools.className='actions';$('.top-tools').append(tools);}
  const user=state?.user;
  tools.innerHTML=user?`<button class="text-button" data-auth="account">${esc(user.username)}${user.is_admin?' · Admin':''}</button><button class="text-button" data-auth="logout">Sign out</button>`:'';
  $('.avatar').textContent=user?user.username[0].toUpperCase():'—';
  $('.avatar').setAttribute('aria-label',user?'Signed in as '+user.username:'Not signed in');
}
function showLogin(setup=false){
  clearAccountState();$('#top-navigation').innerHTML='';accountHeader();
  $('#view').innerHTML=`<section class="panel login-panel"><div class="panel-head"><div><h1>${setup?'Set up your admin account':'Sign in'}</h1><p>${setup?'Create the password for manoj. Other accounts are created by the admin.':'Use the account provided by your admin.'}</p></div></div><form id="account-login" data-setup="${setup}"><div class="form-section"><div class="fields"><label class="field"><span>Username</span><input name="username" autocomplete="username" required maxlength="32" ${setup?'value="manoj" readonly':''}></label><label class="field"><span>Password</span><input name="password" type="password" autocomplete="${setup?'new-password':'current-password'}" required ${setup?'minlength="6"':''} maxlength="128"></label></div><div class="form-error" role="alert"></div></div><div class="form-actions"><button class="button primary" type="submit">${setup?'Create admin and sign in':'Sign in'}</button></div></form></section>`;
}
async function startWorkspace(){
  const session=await api('auth/session');
  if(!session.enabled)return refresh();
  if(!session.user){showLogin(session.setup_required);return;}
  accountSession=session.user;await refresh();
}
function permissionControls(root){
  if(!state?.user)return;
  accountHeader();
  if(isAdmin())return;
  const actions=['refresh-stocks','refresh-universe','refresh-fundamentals','refresh-market-news','fetch-sectors','backtest-history'];
  const selectors=[...actions.map(x=>`[data-action="${x}"]`),
    '[data-company-action="auto-research"]','[data-company-action="pull-fundamentals"]',
    ...['refresh','cycle','interpret','complete-reviews','database-sync','scores','settings'].map(x=>`[data-investor="${x}"]`)];
  root.querySelectorAll(selectors.join(',')).forEach(control=>{control.hidden=true;control.disabled=true;});
}
async function loadAdmin(){
  const generation=accountGeneration;
  try{
    const [users,services]=await Promise.all([api('admin/users'),api('admin/services')]);
    if(generation!==accountGeneration||!isAdmin())return;
    adminData={...users,...services};if(currentView==='admin')render();
  }catch(error){if(currentView==='admin')$('#view').innerHTML=empty('Admin could not load',error.message);}
}
function adminView(){
  if(!isAdmin())return empty('Admin access required','Only manoj can manage accounts and shared connections.');
  if(!adminData){loadAdmin();return heading('Admin','Users and shared service connections.')+'<p role="status">Loading administration…</p>';}
  return heading('Admin','Manage accounts, market data and shared research credentials.')+
    `<section class="panel"><div class="panel-head"><h2>Users</h2></div><div class="panel-body"><div class="table-wrap"><table><thead><tr><th>Username</th><th>Access</th><th>Status</th><th></th></tr></thead><tbody>${adminData.users.map(u=>`<tr><td>${esc(u.username)}</td><td>${u.is_admin?'Admin':'User'}</td><td>${u.enabled?'Enabled':'Disabled'}</td><td>${u.is_admin?'':`<button class="text-button" data-auth="toggle-user" data-user="${esc(u.username)}" data-enabled="${!u.enabled}">${u.enabled?'Disable':'Enable'}</button> <button class="text-button" data-auth="reset-password" data-user="${esc(u.username)}">Reset password</button>`}</td></tr>`).join('')}</tbody></table></div><form id="account-create"><h3>Create user</h3><div class="fields"><label class="field"><span>Username</span><input name="username" required pattern="[a-z][a-z0-9_]{2,31}" minlength="3" maxlength="32" autocomplete="off"></label><label class="field"><span>Initial password</span><input name="password" type="password" required minlength="6" maxlength="128" autocomplete="new-password"></label></div><div class="form-error" role="alert"></div><div class="form-actions"><button class="button primary" type="submit">Create user</button></div></form></div></section>`+
    `<section class="panel"><div class="panel-head"><h2>Shared market data and research credentials</h2></div><div class="panel-body"><p>These connections supply the common workspace. Personal trading credentials are configured in Settings.</p><form id="account-services"><div class="fields"><label class="field"><span>Market-data Upstox token ${adminData.market_token_saved?'· Saved':''}</span><input name="market_token" type="password" minlength="20" maxlength="10000" autocomplete="off" placeholder="Leave blank to retain the saved token"></label><label class="field"><span>Research API key ${adminData.research_key_saved?'· Saved':''}</span><input name="research_key" type="password" minlength="20" maxlength="1000" autocomplete="off" placeholder="Leave blank to retain the saved key"></label><label class="field"><span>Research model</span><input name="research_model" maxlength="100" value="${esc(adminData.research_model)}" placeholder="Configured research model"></label></div><div class="form-error" role="alert"></div><div class="form-actions"><button class="button primary" type="submit">Save shared credentials</button></div></form></div></section>`;
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-auth]');if(!button)return;
  const action=button.dataset.auth;
  try{
    if(action==='logout'){await api('auth/logout','POST',{});showLogin();return;}
    if(action==='account'){modal('Change password',`<form id="account-password"><div class="fields"><label class="field"><span>Current password</span><input name="current_password" type="password" autocomplete="current-password" required maxlength="128"></label><label class="field"><span>New password</span><input name="password" type="password" autocomplete="new-password" minlength="6" maxlength="128" required></label></div><div class="form-error" role="alert"></div><div class="form-actions"><button class="button primary" type="submit">Change password and sign out</button></div></form>`);return;}
    if(action==='toggle-user'){await api('admin/users/'+encodeURIComponent(button.dataset.user),'PUT',{enabled:button.dataset.enabled==='true'});adminData=null;render();return;}
    if(action==='reset-password'){modal('Reset '+button.dataset.user+' password',`<form id="account-reset" data-user="${esc(button.dataset.user)}"><label class="field"><span>New password</span><input name="password" type="password" autocomplete="new-password" minlength="6" maxlength="128" required></label><div class="form-error" role="alert"></div><div class="form-actions"><button class="button primary" type="submit">Reset password and revoke sessions</button></div></form>`);}
  }catch(error){toast(error.message);}
});
document.addEventListener('submit',async event=>{
  const form=event.target;
  if(!['account-login','account-create','account-services','account-password','account-reset'].includes(form.id))return;
  event.preventDefault();event.stopImmediatePropagation();
  const values=Object.fromEntries(new FormData(form)),error=form.querySelector('.form-error'),button=form.querySelector('[type="submit"]');
  button.disabled=true;error.textContent='';
  try{
    if(form.id==='account-login'){
      if(form.dataset.setup==='true')await api('auth/setup','POST',values);
      const login=await api('auth/login','POST',values);accountSession=login.user;form.reset();await refresh();return;
    }
    if(form.id==='account-create'){await api('admin/users','POST',values);form.reset();adminData=null;render();return;}
    if(form.id==='account-services'){await api('admin/services','PUT',Object.fromEntries(Object.entries(values).filter(([,v])=>v.trim())));form.reset();adminData=null;await refresh();return;}
    if(form.id==='account-password'){await api('auth/password','PUT',values);showLogin();return;}
    if(form.id==='account-reset'){await api('admin/users/'+encodeURIComponent(form.dataset.user),'PUT',values);$('#modal').close();toast('Password reset; existing sessions revoked.');}
  }catch(exc){error.textContent=exc.message;}finally{button.disabled=false;}
});
