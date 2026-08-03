document.addEventListener('DOMContentLoaded', function(){
  const btnCheckin = document.getElementById('btn-checkin');
  const btnCheckout = document.getElementById('btn-checkout');
  const status = document.getElementById('asistencia-status');
  const tableBody = document.querySelector('#asistenciaTable tbody');
  const exportForm = document.getElementById('exportForm');

  // helper que incluye CSRF y credenciales para todas las POST
  function _getCsrfHeaders() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = meta ? meta.getAttribute('content') : null;
    const h = { 'X-Requested-With': 'XMLHttpRequest' };
    if (token) h['X-CSRF-Token'] = token;
    return h;
  }

  async function postJson(url, opts){
    const headers = Object.assign({}, _getCsrfHeaders(), (opts && opts.headers) || {});
    const resp = await fetch(url, Object.assign({ method: 'POST', headers: headers, credentials: 'same-origin' }, opts || {}));
    const txt = await resp.text();
    try {
      return JSON.parse(txt);
    } catch (e) {
      return { success: false, error: txt || ('HTTP ' + resp.status), status: resp.status };
    }
  }

    // helpers para convertir ISO UTC <-> input datetime-local (local timezone)
    function isoToLocalDatetimeInput(iso){
      if (!iso) return '';
      try{
        // ensure timezone marker
        if (typeof iso === 'string' && !/[zZ]|[+\-]\d{2}:\d{2}$/.test(iso)) iso = iso + 'Z';
        const d = new Date(iso);
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth()+1).padStart(2,'0');
        const dd = String(d.getDate()).padStart(2,'0');
        const hh = String(d.getHours()).padStart(2,'0');
        const min = String(d.getMinutes()).padStart(2,'0');
        return `${yyyy}-${mm}-${dd}T${hh}:${min}`;
      }catch(e){ return ''; }
    }

    function localInputToISOString(localVal){
      if (!localVal) return null;
      try{
        // localVal expected like 'YYYY-MM-DDTHH:MM'
        const [datePart, timePart] = localVal.split('T');
        if (!datePart || !timePart) return null;
        const [y,m,d] = datePart.split('-').map(x=>parseInt(x,10));
        const [hh,min] = timePart.split(':').map(x=>parseInt(x,10));
        const dt = new Date(y, (m||1)-1, d, hh||0, min||0, 0);
        return dt.toISOString();
      }catch(e){ return null; }
    }

  if (btnCheckin) btnCheckin.addEventListener('click', async function(ev){
    try{ ev && ev.preventDefault(); }catch(e){}
    btnCheckin.disabled = true;
    try {
      const res = await postJson('/asistencia/checkin');
      if (res && res.success) {
        // Update UI in-place when server returns the created record
        try {
          const rec = res.record;
          if (rec) {
            // update status panel
            const st = document.getElementById('asistencia-status');
            if (st) {
              if (!rec.check_out) {
                const t = rec.check_in ? new Date(rec.check_in).toLocaleTimeString() : '';
                st.textContent = `Tienes entrada registrada a las ${t} (sin salida todavía).`;
              } else {
                st.textContent = 'No tienes entrada para hoy.';
              }
            }
            // insert or replace row in table
            if (tableBody) {
              const existing = tableBody.querySelector(`tr[data-id="${rec.id}"]`);
              const hasActions = document.querySelectorAll('#asistenciaTable thead th').length > 6;
              const rowHtml = `
                <tr data-id="${rec.id}" data-username="${rec.username || ''}" data-role="${rec.role || ''}" data-date="${rec.date || ''}" data-checkin="${rec.check_in || ''}" data-checkout="${rec.check_out || ''}" data-note="${rec.note || ''}" data-status="${rec.status || ''}">
                  <td>${rec.username || ''}</td>
                  <td>${rec.role || ''}</td>
                  <td>${rec.date || ''}</td>
                  <td class="td-checkin">${rec.check_in ? (rec.check_in.replace('T',' ').split('.')[0]) : ''}</td>
                  <td class="td-checkout">${rec.check_out ? (rec.check_out.replace('T',' ').split('.')[0]) : ''}</td>
                  <td class="td-status"></td>
                  <td class="td-shift"></td>
                  <td class="td-note">${rec.note || ''}</td>
                  ${hasActions ? '<td class="td-actions"><div class="btn-group" role="group"><button class="btn btn-sm btn-outline-primary btn-edit" data-id="'+rec.id+'">Editar</button><button class="btn btn-sm btn-outline-danger btn-delete" data-id="'+rec.id+'">Borrar</button></div></td>' : ''}
                </tr>
              `;
              if (existing) {
                existing.outerHTML = rowHtml;
                const newTr = tableBody.querySelector(`tr[data-id="${rec.id}"]`);
                if (newTr) formatRowTimes(newTr);
              } else {
                tableBody.insertAdjacentHTML('afterbegin', rowHtml);
                const newTr = tableBody.querySelector(`tr[data-id="${rec.id}"]`);
                if (newTr) formatRowTimes(newTr);
              }
            }
          }
        } catch (e) {
          console.error('Actualizar UI fallo', e);
          window.location.reload();
          return;
        }
        // adjust buttons state
        try {
          if (res.record && !res.record.check_out) {
            btnCheckin.disabled = true;
            if (btnCheckout) btnCheckout.disabled = false;
          } else {
            if (btnCheckin) btnCheckin.disabled = false;
            if (btnCheckout) btnCheckout.disabled = true;
          }
        } catch (e) {}
        return;
      } else {
        const err = (res && (res.error || res.message)) || 'Error marcando entrada';
        alert(err);
      }
    } catch (e) {
      alert('Error de red: ' + e.message);
    }
    btnCheckin.disabled = false;
  });

  if (btnCheckout) btnCheckout.addEventListener('click', async function(ev){
    try{ ev && ev.preventDefault(); }catch(e){}
    btnCheckout.disabled = true;
    try {
      const res = await postJson('/asistencia/checkout');
      if (res && res.success) {
        // Update UI in-place when server returns the updated record
        try {
          const rec = res.record;
          if (rec) {
            const st = document.getElementById('asistencia-status');
            if (st) {
              if (!rec.check_out) {
                const t = rec.check_in ? new Date(rec.check_in).toLocaleTimeString() : '';
                st.textContent = `Tienes entrada registrada a las ${t} (sin salida todavía).`;
              } else {
                st.textContent = 'No tienes entrada para hoy.';
              }
            }
            if (tableBody) {
              const existing = tableBody.querySelector(`tr[data-id="${rec.id}"]`);
              if (existing) {
                existing.setAttribute('data-checkout', rec.check_out || '');
                existing.setAttribute('data-note', rec.note || '');
                formatRowTimes(existing);
                const noteEl = existing.querySelector('.td-note'); if (noteEl) noteEl.textContent = rec.note || '';
              } else {
                // fallback: prepend new row
                const hasActions = document.querySelectorAll('#asistenciaTable thead th').length > 6;
                const rowHtml = `
                  <tr data-id="${rec.id}" data-username="${rec.username || ''}" data-role="${rec.role || ''}" data-date="${rec.date || ''}" data-checkin="${rec.check_in || ''}" data-checkout="${rec.check_out || ''}" data-note="${rec.note || ''}" data-status="${rec.status || ''}">
                    <td>${rec.username || ''}</td>
                    <td>${rec.role || ''}</td>
                    <td>${rec.date || ''}</td>
                    <td class="td-checkin">${rec.check_in ? (rec.check_in.replace('T',' ').split('.')[0]) : ''}</td>
                    <td class="td-checkout">${rec.check_out ? (rec.check_out.replace('T',' ').split('.')[0]) : ''}</td>
                    <td class="td-status"></td>
                    <td class="td-shift"></td>
                    <td class="td-note">${rec.note || ''}</td>
                    ${hasActions ? '<td class="td-actions"><div class="btn-group" role="group"><button class="btn btn-sm btn-outline-primary btn-edit" data-id="'+rec.id+'">Editar</button><button class="btn btn-sm btn-outline-danger btn-delete" data-id="'+rec.id+'">Borrar</button></div></td>' : ''}
                  </tr>
                `;
                tableBody.insertAdjacentHTML('afterbegin', rowHtml);
                const newTr = tableBody.querySelector(`tr[data-id="${rec.id}"]`);
                if (newTr) formatRowTimes(newTr);
              }
            }
          }
        } catch (e) {
          console.error('Actualizar UI fallo', e);
          window.location.reload();
          return;
        }
        try {
          if (res.record && !res.record.check_out) {
            btnCheckin.disabled = true;
            if (btnCheckout) btnCheckout.disabled = false;
          } else {
            if (btnCheckin) btnCheckin.disabled = false;
            if (btnCheckout) btnCheckout.disabled = true;
          }
        } catch (e) {}
        return;
      } else {
        const err2 = (res && (res.error || res.message)) || 'Error marcando salida';
        alert(err2);
      }
    } catch (e) {
      alert('Error de red: ' + e.message);
    }
    btnCheckout.disabled = false;
  });

  if (exportForm) exportForm.addEventListener('submit', function(e){
    e.preventDefault();
    const form = new FormData(exportForm);
    const params = new URLSearchParams();
    for (let [k,v] of form.entries()) if (v) params.append(k,v);
    window.location = '/asistencia/export.csv?' + params.toString();
  });

  // Admin: edit/delete handlers
  let editModalEl = document.getElementById('asistenciaEditModal');
  let editModal = null;
  const editForm = document.getElementById('editAttendanceForm');
  const editSaveBtn = document.getElementById('editSaveBtn');

  function ensureEditModal(){
    if (!editModalEl) editModalEl = document.getElementById('asistenciaEditModal');
    if (!editModal && window.bootstrap && window.bootstrap.Modal && editModalEl) {
      try { editModal = new bootstrap.Modal(editModalEl); } catch(e){ editModal = null; }
    }
  }

  // Fallback show/hide when bootstrap modal not available
  let _backdrop = null;
  function _createBackdrop(){
    _backdrop = document.createElement('div');
    _backdrop.className = 'modal-backdrop fade show';
    document.body.appendChild(_backdrop);
  }
  function showModalFallback(){
    if (!editModalEl) return;
    editModalEl.classList.add('show');
    editModalEl.style.display = 'block';
    editModalEl.removeAttribute('aria-hidden');
    document.body.classList.add('modal-open');
    if (!_backdrop) _createBackdrop();
  }
  function hideModalFallback(){
    if (!editModalEl) return;
    editModalEl.classList.remove('show');
    editModalEl.style.display = 'none';
    editModalEl.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('modal-open');
    if (_backdrop) { _backdrop.remove(); _backdrop = null; }
  }

  function showModal(){
    ensureEditModal();
    if (editModal && typeof editModal.show === 'function') {
      editModal.show();
    } else {
      showModalFallback();
    }
  }

  function hideModal(){
    if (editModal && typeof editModal.hide === 'function') {
      editModal.hide();
    } else {
      hideModalFallback();
    }
  }

  function formatLocalDateTime(iso){
    if (!iso) return '';
    try{
      // If ISO string lacks timezone info (no trailing Z or +hh:mm), treat it as UTC
      if (typeof iso === 'string' && !/[zZ]|[+\-]\d{2}:\d{2}$/.test(iso)) {
        iso = iso + 'Z';
      }
      const d = new Date(iso);
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth()+1).padStart(2,'0');
      const dd = String(d.getDate()).padStart(2,'0');
      const hh = String(d.getHours()).padStart(2,'0');
      const min = String(d.getMinutes()).padStart(2,'0');
      return `${hh}:${min}`;
    }catch(e){ return iso; }
  }

  function formatRowTimes(tr){
    try{
      const ci = tr.getAttribute('data-checkin');
      const co = tr.getAttribute('data-checkout');
      const ciCell = tr.querySelector('.td-checkin');
      const coCell = tr.querySelector('.td-checkout');
      const statusCell = tr.querySelector('.td-status');
      const shiftCell = tr.querySelector('.td-shift');
      if (ciCell && ci) ciCell.textContent = formatLocalDateTime(ci);
      if (coCell) coCell.textContent = co ? formatLocalDateTime(co) : '';
      // compute Estado and Turno based on check-in
      try{
        const info = determineShiftAndStatus(ci);
        if (statusCell) statusCell.textContent = info.status || '';
        if (shiftCell) shiftCell.textContent = info.shift || '';
      }catch(e){}
    }catch(e){/* ignore */}
  }

  function determineShiftAndStatus(iso){
    // Returns { shift: 'Mañana (08:00-17:00)'|'Tarde (18:00-21:00)'|'Otro'|'', status: 'Asistencia'|'Retraso'|'' }
    if (!iso) return { shift: '', status: '' };
    try{
      if (typeof iso === 'string' && !/[zZ]|[+\-]\d{2}:\d{2}$/.test(iso)) iso = iso + 'Z';
      const d = new Date(iso);
      const h = d.getHours();
      const m = d.getMinutes();
      // morning shift
      if ((h > 8 && h < 17) || (h === 8) || (h === 17 && m === 0)){
        const expected = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 8, 0, 0);
        const delayMin = Math.max(0, Math.round((d - expected) / 60000));
        return { shift: 'Mañana (08:00-17:00)', status: delayMin > 0 ? 'Retraso' : 'Asistencia' };
      }
      // afternoon shift
      if (h >= 18 && h < 21){
        const expected = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 18, 0, 0);
        const delayMin = Math.max(0, Math.round((d - expected) / 60000));
        return { shift: 'Tarde (18:00-21:00)', status: delayMin > 0 ? 'Retraso' : 'Asistencia' };
      }
      return { shift: 'Otro', status: 'Asistencia' };
    }catch(e){ return { shift: '', status: '' }; }
  }

  function formatAllTimes(){
    if (tableBody) {
      tableBody.querySelectorAll('tr').forEach(tr=>formatRowTimes(tr));
    }
    try{
      const st = document.getElementById('asistencia-status');
      if (st) {
        const open = st.getAttribute('data-open-checkin');
        if (open) {
          const t = formatLocalDateTime(open);
          st.textContent = `Tienes entrada registrada a las ${t} (sin salida todavía).`;
        }
      }
    }catch(e){}
  }

  try{ formatAllTimes(); }catch(e){}

  // Global fallback handler: ensure Edit button always responds (capture phase)
  document.addEventListener('click', function(ev){
    const be = ev.target.closest && ev.target.closest('.btn-edit');
    if (!be) return;
    ev.preventDefault(); ev.stopPropagation();
    const id = be.getAttribute('data-id') || (be.closest && be.closest('tr') && be.closest('tr').getAttribute('data-id'));
    const tr = be.closest('tr');
    const username = tr ? (tr.getAttribute('data-username') || '') : '';
    const role = tr ? (tr.getAttribute('data-role') || '') : '';
    const checkin = tr ? (tr.getAttribute('data-checkin') || '') : '';
    const checkout = tr ? (tr.getAttribute('data-checkout') || '') : '';
    const note = tr ? (tr.getAttribute('data-note') || '') : '';
    const elId = document.getElementById('edit-id');
    const elUser = document.getElementById('edit-username');
    const elRole = document.getElementById('edit-role');
    const elCheckin = document.getElementById('edit-checkin');
    const elCheckout = document.getElementById('edit-checkout');
    const elNote = document.getElementById('edit-note');
    const elStatus = document.getElementById('edit-status');
    if (elId) elId.value = id || '';
    if (elUser) elUser.value = username;
    if (elRole) elRole.value = role;
    if (elCheckin) elCheckin.value = checkin ? isoToLocalDatetimeInput(checkin) : '';
    if (elCheckout) elCheckout.value = checkout ? isoToLocalDatetimeInput(checkout) : '';
    if (elNote) elNote.value = note;
    if (elStatus) elStatus.value = tr ? (tr.getAttribute('data-status') || '') : '';
    // try to show modal; if not, immediate prompt fallback
    showModal();
    setTimeout(()=>{
      try{
        const visible = editModalEl && (editModalEl.classList.contains('show') || editModalEl.style.display === 'block');
        if (!visible) {
          // Preferir abrir el editor inline si está disponible (definido en la plantilla)
          try{
            if (typeof window.openSimpleEdit === 'function') {
              window.openSimpleEdit(be);
              return;
            }
          }catch(e){}
          try{
            if (typeof openSimpleEdit === 'function') {
              openSimpleEdit(be);
              return;
            }
          }catch(e){}
          // Último recurso: intentar abrir el editor inline; si no está disponible, avisar
          try{ if (typeof window.openSimpleEdit === 'function') { window.openSimpleEdit(be); return; } }catch(e){}
          alert('Editor de edición no disponible. Recarga la página e inténtalo de nuevo.');
        }
      }catch(e){/*ignore*/}
    }, 200);
  }, true);

  // Guardar cambios desde el modal de edición
  if (editSaveBtn) {
    editSaveBtn.addEventListener('click', async function(ev){
      try{ ev && ev.preventDefault(); }catch(e){}
      const id = (document.getElementById('edit-id') || {}).value;
      if (!id) { alert('ID de registro no disponible'); return; }
      const payload = {};
      try{
        const ciVal = (document.getElementById('edit-checkin') || {}).value;
        const coVal = (document.getElementById('edit-checkout') || {}).value;
        const statusVal = (document.getElementById('edit-status') || {}).value;
        const noteVal = (document.getElementById('edit-note') || {}).value;
        const roleVal = (document.getElementById('edit-role') || {}).value;
        if (typeof ciVal !== 'undefined') payload.check_in = localInputToISOString(ciVal);
        if (typeof coVal !== 'undefined') payload.check_out = localInputToISOString(coVal);
        if (typeof statusVal !== 'undefined') payload.status = statusVal || null;
        if (typeof noteVal !== 'undefined') payload.note = noteVal || null;
        if (typeof roleVal !== 'undefined') payload.role = roleVal || null;
      }catch(e){/* ignore */}

      try{
        const res = await postJson(`/asistencia/${id}/edit`, { headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
        const ok = res && (res.ok || res.success || res.success === true || res.status === 200 || res.success === 'true');
        const rec = res && (res.record || res);
        if (ok && rec) {
          // support wrappers where record is nested
          const record = rec.record ? rec.record : rec;
          const tr = document.querySelector(`tr[data-id="${id}"]`);
          if (tr) {
            if ('check_in' in record) tr.setAttribute('data-checkin', record.check_in || '');
            if ('check_out' in record) tr.setAttribute('data-checkout', record.check_out || '');
            if ('note' in record) tr.setAttribute('data-note', record.note || '');
            if ('status' in record) tr.setAttribute('data-status', record.status || '');
            if ('role' in record) tr.setAttribute('data-role', record.role || '');
            // actualizar celdas visibles
            try{
              const ciCell = tr.querySelector('.td-checkin'); if (ciCell) ciCell.textContent = record.check_in ? formatLocalDateTime(record.check_in) : '';
              const coCell = tr.querySelector('.td-checkout'); if (coCell) coCell.textContent = record.check_out ? formatLocalDateTime(record.check_out) : '';
              const noteEl = tr.querySelector('.td-note'); if (noteEl) noteEl.textContent = record.note || '';
              const statusEl = tr.querySelector('.td-status'); if (statusEl) statusEl.textContent = record.status || (record.check_in ? determineShiftAndStatus(record.check_in).status : '');
              const shiftEl = tr.querySelector('.td-shift'); if (shiftEl) shiftEl.textContent = record.check_in ? determineShiftAndStatus(record.check_in).shift : '';
            }catch(e){/* ignore */}
          }
          hideModal();
          try{ alert('Registro actualizado.'); }catch(e){}
          return;
        }
        // error
        const errMsg = (res && (res.error || res.message)) || 'Error guardando registro';
        alert(errMsg);
      }catch(e){ alert('Error de red: ' + (e && e.message ? e.message : e)); }
    });
  }

  // delegate clicks for edit/delete
  if (tableBody) {
    tableBody.addEventListener('click', function(ev){
      const btn = ev.target.closest('.btn-edit, .btn-delete');
      if (!btn) return;
      const tr = btn.closest('tr');
      const id = btn.getAttribute('data-id') || tr.getAttribute('data-id');
      if (btn.classList.contains('btn-edit')) {
        // populate modal with data-* from row
        const username = tr.getAttribute('data-username') || '';
        const role = tr.getAttribute('data-role') || '';
        const checkin = tr.getAttribute('data-checkin') || '';
        const checkout = tr.getAttribute('data-checkout') || '';
        const note = tr.getAttribute('data-note') || '';
        document.getElementById('edit-id').value = id;
        document.getElementById('edit-username').value = username;
        document.getElementById('edit-role').value = role;
        document.getElementById('edit-checkin').value = checkin ? isoToLocalDatetimeInput(checkin) : '';
        document.getElementById('edit-checkout').value = checkout ? isoToLocalDatetimeInput(checkout) : '';
        document.getElementById('edit-note').value = note;
        // status may be persisted or computed; prefer persisted
        try{ document.getElementById('edit-status').value = tr.getAttribute('data-status') || ''; }catch(e){}
        showModal();
        // If modal didn't appear (bootstrap missing or CSS issue), open inline editor if available
        setTimeout(()=>{
          try{
            const visible = editModalEl && (editModalEl.classList.contains('show') || editModalEl.style.display === 'block');
            if (!visible) {
              try{
                if (typeof window.openSimpleEdit === 'function') { window.openSimpleEdit(btn); return; }
              }catch(e){}
              try{
                if (typeof openSimpleEdit === 'function') { openSimpleEdit(btn); return; }
              }catch(e){}
              // Último recurso: intentar abrir el editor inline; si no está disponible, avisar
              try{ if (typeof window.openSimpleEdit === 'function') { window.openSimpleEdit(btn); return; } }catch(e){}
              alert('Editor de edición no disponible. Recarga la página e inténtalo de nuevo.');
            }
          }catch(e){/* ignore */}
        }, 350);
        return;
      }
      if (btn.classList.contains('btn-delete')) {
        if (!confirm('Borrar este registro? Esta acción es irreversible.')) return;
        fetch(`/asistencia/${id}/delete`, { method: 'POST', headers: _getCsrfHeaders(), credentials: 'same-origin' })
          .then(async r=>{ const txt = await r.text(); try{ return JSON.parse(txt); }catch(e){ return { ok:false, error: txt || ('HTTP '+r.status) }; } })
          .then(res=>{
            if (res && res.ok) {
              tr.remove();
            } else {
              alert(res.error || res.message || 'Error borrando');
            }
          }).catch(e=>alert('Error de red: '+e.message));
      }
    });
  }
  // (handler para guardar definido arriba) — evitar duplicados
});

// --- Simple standalone edit modal (bootstrap-independent) ---
(function(){
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const CSRF = csrfMeta ? csrfMeta.getAttribute('content') : null;

  function createSimpleModal(){
    if (document.getElementById('simple-edit-modal')) return;
    const modal = document.createElement('div');
    modal.id = 'simple-edit-modal';
    modal.style.position = 'fixed';
    modal.style.left = '0'; modal.style.top = '0'; modal.style.right = '0'; modal.style.bottom = '0';
    modal.style.display = 'none'; modal.style.alignItems = 'center'; modal.style.justifyContent = 'center';
    modal.style.zIndex = '1050';
    modal.innerHTML = `
      <div style="background:rgba(0,0,0,0.5);position:absolute;inset:0"></div>
      <div style="background:#fff;border-radius:8px;padding:16px;max-width:420px;width:95%;box-shadow:0 6px 18px rgba(0,0,0,0.2);position:relative;z-index:2">
        <h5 style="margin:0 0 8px 0">Editar asistencia</h5>
        <div style="margin-bottom:8px"><label style="font-size:12px">Entrada</label><input id="simple-edit-checkin" style="width:100%;padding:6px;margin-top:4px" placeholder="YYYY-MM-DD HH:MM"></div>
        <div style="margin-bottom:8px"><label style="font-size:12px">Salida</label><input id="simple-edit-checkout" style="width:100%;padding:6px;margin-top:4px" placeholder="YYYY-MM-DD HH:MM"></div>
        <div style="margin-bottom:8px"><label style="font-size:12px">Estado</label><select id="simple-edit-status" style="width:100%;padding:6px;margin-top:4px"><option value="">(automático)</option><option value="Asistencia">Asistencia</option><option value="Retraso">Retraso</option><option value="Otro">Otro</option></select></div>
        <div style="margin-bottom:8px"><label style="font-size:12px">Nota</label><input id="simple-edit-note" style="width:100%;padding:6px;margin-top:4px" placeholder="Nota"></div>
        <div style="text-align:right;margin-top:10px"><button id="simple-edit-cancel" style="margin-right:8px">Cancelar</button><button id="simple-edit-save">Guardar</button></div>
      </div>
    `;
    document.body.appendChild(modal);
    document.getElementById('simple-edit-cancel').addEventListener('click', hideSimpleModal);
    document.getElementById('simple-edit-save').addEventListener('click', saveSimpleModal);
  }

  function showSimpleModal(data){
    createSimpleModal();
    const modal = document.getElementById('simple-edit-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    document.getElementById('simple-edit-checkin').value = data.checkin || '';
    document.getElementById('simple-edit-checkout').value = data.checkout || '';
    try{ document.getElementById('simple-edit-status').value = data.status || ''; }catch(e){}
    document.getElementById('simple-edit-note').value = data.note || '';
    modal.dataset.attId = data.id || '';
  }

  function hideSimpleModal(){
    const modal = document.getElementById('simple-edit-modal');
    if (!modal) return;
    modal.style.display = 'none';
    modal.dataset.attId = '';
  }

  async function saveSimpleModal(){
    const modal = document.getElementById('simple-edit-modal');
    if (!modal) return;
    const id = modal.dataset.attId;
    const rawIn = document.getElementById('simple-edit-checkin').value.trim() || null;
    const rawOut = document.getElementById('simple-edit-checkout').value.trim() || null;
    const payload = { check_in: localInputToISOString(rawIn), check_out: localInputToISOString(rawOut), status: (document.getElementById('simple-edit-status') ? document.getElementById('simple-edit-status').value : null), note: document.getElementById('simple-edit-note').value.trim() || null };
    const headers = Object.assign({'Content-Type':'application/json'}, _getCsrfHeaders());
    try{
      const resp = await fetch(`/asistencia/${id}/edit`, { method: 'POST', headers: headers, body: JSON.stringify(payload), credentials: 'same-origin' });
      const text = await resp.text();
      let j = null;
      try { j = JSON.parse(text); } catch(e) { j = { ok: false, error: text || ('HTTP ' + resp.status) }; }
      if (j && j.ok && j.record){
        // update row
        const tr = document.querySelector(`tr[data-id="${id}"]`);
        if (tr){
          if (j.record.check_in) tr.setAttribute('data-checkin', j.record.check_in);
          if (j.record.check_out) tr.setAttribute('data-checkout', j.record.check_out);
          if (j.record.note !== undefined) tr.setAttribute('data-note', j.record.note || '');
          if (j.record.status !== undefined) tr.setAttribute('data-status', j.record.status || '');
          formatRowTimes(tr);
          const noteEl = tr.querySelector('.td-note'); if (noteEl) noteEl.textContent = j.record.note || '';
          const statusEl = tr.querySelector('.td-status'); if (statusEl) statusEl.textContent = j.record.status || '';
        }
        hideSimpleModal();
        return;
      } else {
        alert('Error guardando: ' + (j && (j.error || j.message) ? (j.error || j.message) : 'respuesta inválida'));
      }
    }catch(e){ alert('Error de red: '+e.message); }
  }

  // Attach handler: open our simple modal when Edit clicked
  document.addEventListener('click', function(ev){
    const btn = ev.target.closest && ev.target.closest('.btn-edit');
    if (!btn) return;
    ev.preventDefault();
    const tr = btn.closest('tr');
    const id = btn.getAttribute('data-id') || (tr && tr.getAttribute('data-id'));
    const data = { id: id, checkin: tr ? (tr.getAttribute('data-checkin') || '') : '', checkout: tr ? (tr.getAttribute('data-checkout') || '') : '', note: tr ? (tr.getAttribute('data-note') || '') : '' };
    // normalize to display format
    try{ if (data.checkin) data.checkin = data.checkin.replace('T',' ').split('.')[0]; if (data.checkout) data.checkout = data.checkout.replace('T',' ').split('.')[0]; }catch(e){}
    showSimpleModal(data);
  });
})();
