const state = {
  config: null,
  selectedDate: null,
  dates: [],
  currentBusy: null,
  currentSlots: [],
  pendingSlot: null,
  lastTicket: null
};

const dayTabsEl = document.getElementById('dayTabs');
const courtsGridEl = document.getElementById('courtsGrid');
const bookingModal = document.getElementById('bookingModal');
const successModal = document.getElementById('successModal');
const cancelModal = document.getElementById('cancelModal');
const cancelForm = document.getElementById('cancelForm');
const modalSummary = document.getElementById('modalSummary');
const bookingForm = document.getElementById('bookingForm');
const formError = document.getElementById('formError');
const submitBtn = document.getElementById('submitBtn');
const durationSelect = document.getElementById('durationHours');
const durationHelp = document.getElementById('durationHelp');
const datePicker = document.getElementById('datePicker');
const downloadTicketBtn = document.getElementById('downloadTicketBtn');

init();

async function init() {
  try {
    const res = await fetch('/api/config');
    if (!res.ok) throw new Error('No se pudo cargar la configuración');
    state.config = await res.json();

    const todayIso = localISODate(new Date());
    state.selectedDate = todayIso;
    configureDatePicker(todayIso);
    buildDayTabs(todayIso);
    await selectDate(todayIso, false);
  } catch (err) {
    courtsGridEl.innerHTML = `<div class="closed-message"><h3>No se pudo cargar la disponibilidad</h3><p>${escapeHtml(err.message)}</p></div>`;
  } finally {
    document.getElementById('loadingScreen').classList.add('hidden');
    document.getElementById('appContent').classList.add('visible');
  }

  document.getElementById('closeModal').onclick = () => bookingModal.classList.remove('open');
  document.getElementById('closeSuccess').onclick = () => successModal.classList.remove('open');
  bookingForm.onsubmit = submitBooking;
  durationSelect.onchange = updateBookingSummary;

  document.getElementById('openCancel').onclick = () => {
    document.getElementById('cancelError').textContent = '';
    document.getElementById('cancelSuccess').textContent = '';
    cancelForm.reset();
    cancelModal.classList.add('open');
  };
  document.getElementById('closeCancel').onclick = () => cancelModal.classList.remove('open');
  cancelForm.onsubmit = submitCancel;

  datePicker.onchange = async () => {
    if (!datePicker.value) return;
    buildDayTabs(datePicker.value);
    await selectDate(datePicker.value, false);
  };

  document.getElementById('todayBtn').onclick = async () => {
    const iso = localISODate(new Date());
    buildDayTabs(iso);
    await selectDate(iso, false);
  };

  downloadTicketBtn.onclick = downloadLastTicket;

  [bookingModal, successModal, cancelModal].forEach(modal => {
    modal.addEventListener('click', e => {
      if (e.target === modal) modal.classList.remove('open');
    });
  });
}

function configureDatePicker(todayIso) {
  datePicker.min = todayIso;
  datePicker.max = addDaysISO(todayIso, state.config.bookingHorizonDays ?? 5);
  datePicker.value = todayIso;
}

function buildDayTabs(anchorIso) {
  // La ventana pública es fija: hoy + los siguientes 5 días (6 fechas en total).
  // No se desplaza con la fecha seleccionada para evitar navegar fuera del rango permitido.
  const anchor = parseISODate(datePicker.min || anchorIso);
  const dates = [];
  for (let i = 0; i <= 5; i++) {
    const d = new Date(anchor);
    d.setDate(anchor.getDate() + i);
    const iso = localISODate(d);
    if (datePicker.max && iso > datePicker.max) break;
    dates.push(d);
  }
  state.dates = dates.map(localISODate);

  dayTabsEl.innerHTML = '';
  dates.forEach(d => {
    const iso = localISODate(d);
    const isSunday = d.getDay() === 0;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'day-tab' + (iso === state.selectedDate ? ' active' : '') + (isSunday ? ' sunday' : '');
    btn.innerHTML = `${weekdayShort(d)}<small>${isSunday ? 'Cerrado' : d.getDate() + ' ' + monthShort(d)}</small>`;
    btn.onclick = async () => selectDate(iso, false);
    dayTabsEl.appendChild(btn);
  });
}

async function selectDate(iso, rebuildIfMissing = true) {
  if (datePicker.min && iso < datePicker.min) iso = datePicker.min;
  if (datePicker.max && iso > datePicker.max) iso = datePicker.max;

  state.selectedDate = iso;
  datePicker.value = iso;

  if (rebuildIfMissing && !state.dates.includes(iso)) buildDayTabs(iso);
  syncActiveTab();
  renderSkeleton();

  try {
    const res = await fetch(`/api/availability?date=${encodeURIComponent(iso)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'No se pudo consultar la disponibilidad');

    state.currentSlots = data.slots || [];
    state.currentBusy = data.busy;

    if (data.closed) renderClosed();
    else renderCourts(data.busy, data.slots || []);
  } catch (err) {
    courtsGridEl.innerHTML = `<div class="closed-message"><h3>No se pudo consultar este día</h3><p>${escapeHtml(err.message)}</p></div>`;
  }
}

function syncActiveTab() {
  dayTabsEl.querySelectorAll('.day-tab').forEach((el, index) => {
    el.classList.toggle('active', state.dates[index] === state.selectedDate);
  });
}

function renderSkeleton() {
  courtsGridEl.innerHTML = '';
  state.config.courts.forEach(() => {
    const block = document.createElement('div');
    block.className = 'court-block skeleton-court';
    block.innerHTML = `<h3></h3><div class="skeleton-slots">${
      Array.from({ length: 10 }).map(() => '<div class="skeleton-slot"></div>').join('')
    }</div>`;
    courtsGridEl.appendChild(block);
  });
}

function renderClosed() {
  courtsGridEl.innerHTML = `
    <div class="closed-message">
      <span class="closed-icon">🌙</span>
      <h3>Cerrado los domingos</h3>
      <p>El servicio de canchas no está disponible este día. Elige otra fecha.</p>
    </div>`;
}

function renderCourts(busyMap, slots) {
  const now = new Date();
  const isToday = state.selectedDate === localISODate(now);

  courtsGridEl.innerHTML = '';
  state.config.courts.forEach(court => {
    const block = document.createElement('div');
    block.className = 'court-block';
    block.innerHTML = `<div class="court-title-row"><h3>${court}</h3><span>${slots.length} bloques</span></div>`;
    const slotsEl = document.createElement('div');
    slotsEl.className = 'slots';

    slots.forEach(time => {
      const busy = Boolean(busyMap?.[court]?.[time]);
      const past = isToday && isPastSlot(time, now);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'slot-btn' + (busy ? ' busy' : past ? ' past' : '');
      btn.innerHTML = `<strong>${time}</strong><small>${busy ? 'Ocupado' : past ? 'No disponible' : '1 hora'}</small>`;
      btn.disabled = busy || past;
      btn.onclick = () => openBookingModal(court, time);
      slotsEl.appendChild(btn);
    });

    block.appendChild(slotsEl);
    courtsGridEl.appendChild(block);
  });
}

function isPastSlot(time, now) {
  const [h, m] = time.split(':').map(Number);
  const slotDate = new Date(now);
  slotDate.setHours(h, m, 0, 0);
  return slotDate <= now;
}

function openBookingModal(court, time) {
  state.pendingSlot = { court, time };
  formError.textContent = '';
  bookingForm.reset();

  const twoHourOption = durationSelect.querySelector('option[value="2"]');
  const canTwo = canBookDuration(court, time, 2);
  twoHourOption.disabled = !canTwo;
  durationSelect.value = '1';
  durationHelp.textContent = canTwo
    ? 'Puedes tomar este horario por 1 o 2 horas consecutivas.'
    : 'Desde esta hora solo hay 1 hora consecutiva disponible.';

  updateBookingSummary();
  bookingModal.classList.add('open');
}

function canBookDuration(court, time, hours) {
  const startIndex = state.currentSlots.indexOf(time);
  if (startIndex < 0 || startIndex + hours > state.currentSlots.length) return false;

  const now = new Date();
  const isToday = state.selectedDate === localISODate(now);
  for (let i = 0; i < hours; i++) {
    const slot = state.currentSlots[startIndex + i];
    if (minutesFromTime(slot) !== minutesFromTime(time) + i * 60) return false;
    if (state.currentBusy?.[court]?.[slot]) return false;
    if (isToday && isPastSlot(slot, now)) return false;
  }
  return true;
}

function updateBookingSummary() {
  if (!state.pendingSlot) return;
  const hours = Number(durationSelect.value || 1);
  const end = addMinutesToTime(state.pendingSlot.time, hours * 60);
  modalSummary.textContent = `${state.pendingSlot.court} · ${formatDateLong(state.selectedDate)} · ${state.pendingSlot.time}–${end} hrs`;
}

async function submitBooking(e) {
  e.preventDefault();
  formError.textContent = '';
  submitBtn.disabled = true;
  submitBtn.textContent = 'Reservando...';

  const fd = new FormData(bookingForm);
  const durationHours = Number(fd.get('durationHours'));
  const payload = {
    court: state.pendingSlot.court,
    date: state.selectedDate,
    time: state.pendingSlot.time,
    durationHours,
    firstName: fd.get('firstName').trim(),
    lastName: fd.get('lastName').trim(),
    acceptedNotice: fd.get('acceptNotice') === 'on',
    phone: fd.get('phone').trim(),
    people: Number(fd.get('people')),
    email: fd.get('email').trim()
  };

  if (!canBookDuration(payload.court, payload.time, durationHours)) {
    formError.textContent = 'La disponibilidad cambió o ese bloque ya no permite esa duración. Vuelve a elegir el horario.';
    submitBtn.disabled = false;
    submitBtn.textContent = 'Reservar horario';
    await selectDate(state.selectedDate, false);
    return;
  }

  try {
    const res = await fetch('/api/reservations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'No se pudo reservar');

    bookingModal.classList.remove('open');
    await showSuccess(data);
    await selectDate(state.selectedDate, false);
  } catch (err) {
    formError.textContent = err.message;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Reservar horario';
  }
}

async function submitCancel(e) {
  e.preventDefault();
  const cancelError = document.getElementById('cancelError');
  const cancelSuccess = document.getElementById('cancelSuccess');
  const cancelBtn = document.getElementById('cancelSubmitBtn');
  cancelError.textContent = '';
  cancelSuccess.textContent = '';
  cancelBtn.disabled = true;
  cancelBtn.textContent = 'Cancelando...';

  const fd = new FormData(cancelForm);
  const payload = {
    code: fd.get('code').trim().toUpperCase(),
    phone: fd.get('phone').trim()
  };

  try {
    const res = await fetch('/api/reservations/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'No se pudo cancelar');

    cancelSuccess.textContent = `Listo, se canceló tu reservación en ${data.cancelled.court} el ${formatDateLong(data.cancelled.date)} de ${data.cancelled.time} a ${data.cancelled.endTime}.`;
    cancelForm.reset();
    if (state.selectedDate === data.cancelled.date) await selectDate(state.selectedDate, false);
  } catch (err) {
    cancelError.textContent = err.message;
  } finally {
    cancelBtn.disabled = false;
    cancelBtn.textContent = 'Cancelar reservación';
  }
}

async function showSuccess(reservation) {
  successModal.classList.add('open');
  const emailStatus = document.getElementById('emailStatus');
  emailStatus.textContent = 'Preparando tu pase de acceso…';
  state.lastTicket = null;
  downloadTicketBtn.disabled = true;

  renderConfirmCard(reservation);
  const imageBase64 = await drawTicket(reservation);
  state.lastTicket = { dataUrl: imageBase64, code: reservation.code };
  downloadTicketBtn.disabled = false;

  const waNumber = state.config.whatsapp;
  const text = encodeURIComponent(
    `Hola, IAJU 👋 Reservé una cancha:\nCancha: ${reservation.court}\nFecha: ${formatDateLong(reservation.date)}\nHorario: ${reservation.time}–${reservation.endTime}\nPersonas: ${reservation.people}\nNombre: ${reservation.name}\nCódigo: ${reservation.code}`
  );
  document.getElementById('whatsappBtn').href = `https://wa.me/${waNumber}?text=${text}`;

  emailStatus.textContent = 'Pase listo para descargar. Enviando copia por correo…';
  try {
    const res = await fetch(`/api/reservations/${reservation.id}/email-ticket`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ imageBase64 })
    });
    const data = await res.json();
    emailStatus.textContent = data.emailSent
      ? `Pase listo. También lo enviamos a ${reservation.email}.`
      : `Pase listo para descargar. No se pudo enviar el correo automático; guarda tu código ${reservation.code}.`;
  } catch (_) {
    emailStatus.textContent = `Pase listo para descargar. No se pudo enviar el correo; guarda tu código ${reservation.code}.`;
  }
}

function downloadLastTicket() {
  if (!state.lastTicket) return;
  const a = document.createElement('a');
  a.href = state.lastTicket.dataUrl;
  a.download = `pase-iaju-${state.lastTicket.code}.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function renderConfirmCard(r) {
  const card = document.getElementById('confirmCard');
  card.innerHTML = `
    <div class="confirm-card-header has-logo"><img class="confirm-brand-logo" src="/static/images/iaju-blanco.png" alt="Instituto de la Juventud"></div>
    <div class="confirm-card-body">
      <div class="confirm-row"><span class="k">Nombre</span><span class="v">${escapeHtml(r.name)}</span></div>
      <div class="confirm-row"><span class="k">Cancha</span><span class="v">${escapeHtml(r.court)}</span></div>
      <div class="confirm-row"><span class="k">Fecha</span><span class="v">${escapeHtml(formatDateLong(r.date))}</span></div>
      <div class="confirm-row"><span class="k">Horario</span><span class="v">${escapeHtml(r.time)}–${escapeHtml(r.endTime)} hrs</span></div>
      <div class="confirm-row"><span class="k">Personas</span><span class="v">${escapeHtml(r.people)}</span></div>
      <div class="confirm-row"><span class="k">Código de acceso</span><span class="v code">${escapeHtml(r.code)}</span></div>
      <div class="ticket-notice">INE obligatoria en caseta. Los datos deben coincidir con tu INE; si no coinciden, no se aplicará penalización por esa discrepancia. Palas y pelotas: préstamo hasta las 3:30 p. m., dejando INE.</div>
    </div>`;
}

async function drawTicket(r) {
  const canvas = document.createElement('canvas');
  canvas.width = 1080;
  canvas.height = 1350;
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;

  ctx.fillStyle = '#f6f8fc';
  ctx.fillRect(0, 0, W, H);

  // Tarjeta principal
  roundRect(ctx, 55, 55, W - 110, H - 110, 38, '#ffffff');

  // Encabezado institucional
  const grad = ctx.createLinearGradient(55, 55, W - 55, 55);
  grad.addColorStop(0, '#3cb4e5');
  grad.addColorStop(1, '#003DA5');
  ctx.save();
  roundedClip(ctx, 55, 55, W - 110, 250, 38, true, false);
  ctx.fillStyle = grad;
  ctx.fillRect(55, 55, W - 110, 250);
  ctx.restore();

  try {
    const logo = await loadImage('/static/images/iaju-blanco.png');
    const maxW = 520;
    const maxH = 115;
    const ratio = Math.min(maxW / logo.width, maxH / logo.height);
    ctx.drawImage(logo, 105, 105, logo.width * ratio, logo.height * ratio);
  } catch (_) {
    ctx.fillStyle = '#ffffff';
    ctx.font = '700 42px Poppins, Arial';
    ctx.fillText('Instituto de la Juventud', 105, 160);
  }

  ctx.fillStyle = 'rgba(255,255,255,.92)';
  ctx.font = '600 24px Inter, Arial';
  ctx.textAlign = 'right';
  ctx.fillText('CANCHAS DE PADEL', W - 105, 150);
  ctx.font = '500 19px Inter, Arial';
  ctx.fillText('Pase digital de acceso', W - 105, 187);
  ctx.textAlign = 'left';

  const colors = ['#df1683', '#c2d500', '#3cb4e5', '#003DA5', '#ffcd00'];
  const stripeW = (W - 110) / colors.length;
  colors.forEach((color, i) => {
    ctx.fillStyle = color;
    ctx.fillRect(55 + stripeW * i, 290, stripeW + 1, 14);
  });

  ctx.fillStyle = '#003DA5';
  ctx.font = '800 42px Poppins, Arial';
  ctx.fillText('RESERVACIÓN CONFIRMADA', 105, 385);
  ctx.fillStyle = '#5b6b8c';
  ctx.font = '500 21px Inter, Arial';
  ctx.fillText('Presenta esta imagen al ingresar a las instalaciones.', 105, 430);

  // Código destacado
  roundRect(ctx, 105, 480, W - 210, 150, 26, '#eef6ff');
  ctx.fillStyle = '#5b6b8c';
  ctx.font = '700 18px Inter, Arial';
  ctx.fillText('CÓDIGO DE ACCESO', 140, 525);
  ctx.fillStyle = '#003DA5';
  ctx.font = '800 64px Poppins, Arial';
  ctx.letterSpacing = '8px';
  ctx.fillText(String(r.code), 140, 595);
  ctx.letterSpacing = '0px';

  const details = [
    ['NOMBRE', r.name],
    ['CANCHA', r.court],
    ['FECHA', formatDateLong(r.date)],
    ['HORARIO', `${r.time}–${r.endTime} hrs`],
    ['PERSONAS', String(r.people)]
  ];

  let y = 700;
  details.forEach(([label, value]) => {
    ctx.fillStyle = '#5b6b8c';
    ctx.font = '700 17px Inter, Arial';
    ctx.fillText(label, 115, y);
    ctx.fillStyle = '#14213d';
    ctx.font = '700 30px Poppins, Arial';
    drawFittedText(ctx, String(value), 115, y + 42, W - 300, 30, 23);
    ctx.strokeStyle = '#e4e9f2';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(115, y + 68);
    ctx.lineTo(W - 115, y + 68);
    ctx.stroke();
    y += 112;
  });

  roundRect(ctx, 105, 1200, W - 210, 90, 18, '#f2f8ff');
  ctx.fillStyle = '#003DA5';
  ctx.font = '700 17px Inter, Arial';
  ctx.textAlign = 'center';
  ctx.fillText('INE en caseta · Datos idénticos a la INE', W / 2, 1228);
  ctx.font = '500 15px Inter, Arial';
  ctx.fillText('Si no coinciden, no se aplicará penalización por esa discrepancia.', W / 2, 1251);
  ctx.fillText('Palas y pelotas hasta 3:30 p. m. · Requieren dejar INE', W / 2, 1274);
  ctx.textAlign = 'left';

  return canvas.toDataURL('image/png');
}

function roundRect(ctx, x, y, width, height, radius, fillStyle) {
  ctx.beginPath();
  ctx.roundRect(x, y, width, height, radius);
  ctx.fillStyle = fillStyle;
  ctx.fill();
}

function roundedClip(ctx, x, y, width, height, radius, topOnly = false) {
  ctx.beginPath();
  if (!topOnly) {
    ctx.roundRect(x, y, width, height, radius);
  } else {
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height);
    ctx.lineTo(x, y + height);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
  }
  ctx.closePath();
  ctx.clip();
}

function drawFittedText(ctx, text, x, y, maxWidth, startSize, minSize) {
  let size = startSize;
  while (size > minSize) {
    ctx.font = `700 ${size}px Poppins, Arial`;
    if (ctx.measureText(text).width <= maxWidth) break;
    size -= 1;
  }
  ctx.fillText(text, x, y);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[ch]);
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

function localISODate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function parseISODate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d, 12, 0, 0, 0);
}

function addDaysISO(iso, days) {
  const d = parseISODate(iso);
  d.setDate(d.getDate() + days);
  return localISODate(d);
}

function weekdayShort(d) {
  return d.toLocaleDateString('es-MX', { weekday: 'short' }).replace('.', '');
}

function monthShort(d) {
  return d.toLocaleDateString('es-MX', { month: 'short' }).replace('.', '');
}

function formatDateLong(iso) {
  const date = parseISODate(iso);
  return date.toLocaleDateString('es-MX', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

function minutesFromTime(time) {
  const [h, m] = time.split(':').map(Number);
  return h * 60 + m;
}

function addMinutesToTime(time, minutes) {
  const total = minutesFromTime(time) + minutes;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}
