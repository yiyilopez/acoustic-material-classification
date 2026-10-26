"""Segmentación preliminar; conserva índices y amplitud, sin aceptar eventos."""

import csv
import html
import json
import os
from pathlib import Path

import numpy as np
import soundfile as sf

from .inspection import sha256_file
from .metadata import SCHEMAS
from .paths import contained_path, check_output_folder


SETTINGS = dict(bloque_s=0.005, factor_fondo=6, fraccion_pico=0.035,
                separacion_s=0.35, pre_s=0.05, silencio_s=0.10,
                factor_final=2.5, fraccion_final=0.015)


def detect_candidates(signal, fs, settings=None):
    """RMS por bloques; máximos separados, con límites de contexto provisionales.

    El final requiere 100 ms bajo el umbral de fondo/cola. Nunca atraviesa
    el preinicio del siguiente evento. Estos límites no definen aún el D90.
    """
    cfg = SETTINGS | (settings or {})
    x = np.asarray(signal)
    if x.ndim != 1 or not np.isfinite(x).all() or fs <= 0:
        raise ValueError('Se requiere audio mono finito y frecuencia positiva.')
    block = max(1, round(fs * cfg['bloque_s']))
    count = len(x) // block
    if count < 3:
        return [], dict(bloque_muestras=block, fondo_rms=0, umbral_rms=0)
    env = np.sqrt(np.mean(x[:count * block].reshape(count, block) ** 2, axis=1))
    noise = float(np.quantile(env, .2))
    threshold = max(noise * cfg['factor_fondo'], float(env.max()) * cfg['fraccion_pico'])
    maxima = np.flatnonzero((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) &
                           (env[1:-1] > threshold)) + 1
    selected = []
    for k in sorted(maxima, key=lambda i: (-env[i], i)):
        if all(abs(k - j) * block / fs >= cfg['separacion_s'] for j in selected):
            selected.append(int(k))
    selected.sort()
    starts = []
    for peak in selected:
        # Buscar el frente sin avanzar sobre el bloque de máximo.
        onset = peak
        level = max(noise * 3, float(env[peak]) * .10)
        while onset > 0 and env[onset - 1] > level and (peak - onset) * block / fs < .3:
            onset -= 1
        starts.append(max(0, onset * block - round(cfg['pre_s'] * fs)))
    rows = []
    quiet_blocks = max(1, int(np.ceil(cfg['silencio_s'] * fs / block)))
    for index, peak in enumerate(selected):
        start = starts[index]
        limit = starts[index + 1] if index + 1 < len(starts) else len(x)
        level = max(noise * cfg['factor_final'], float(env[peak]) * cfg['fraccion_final'])
        quiet = 0
        end = limit
        found = False
        for k in range(peak + max(1, round(.03 * fs / block)), min(count, limit // block)):
            quiet = quiet + 1 if env[k] < level else 0
            if quiet >= quiet_blocks:
                end = min(limit, (k + 1) * block)
                found = True
                break
        flags = []
        ratio = float(env[peak] / max(noise, np.finfo(float).tiny))
        if ratio < 8:
            flags.append('Evento débil respecto al fondo: confirmar si es un golpe.')
        if peak * block / fs < 1 or (len(x) - peak * block) / fs < 1:
            flags.append('Cercano al inicio/final: posible manipulación.')
        if not found:
            flags.append('Cola limitada por otro evento o el final del archivo.')
        rows.append(dict(inicio_muestra=start, fin_muestra=end,
                         pico_muestra=peak * block + block // 2,
                         pico_rms=float(env[peak]), razon_pico_fondo=ratio,
                         avisos=flags))
    return rows, dict(bloque_muestras=block, fondo_rms=noise, umbral_rms=threshold)


def segment_pilot(root: Path):
    raw = root / 'datos/originales'
    decoded = root / 'datos/procesados/decodificados'
    output = root / 'resultados/segmentacion_piloto'
    clips = root / 'datos/procesados/segmentos_piloto'
    metadata = root / 'datos/metadatos/impactos.csv'
    check_output_folder(raw, output)
    check_output_folder(raw, clips)
    with metadata.open(newline='', encoding='utf-8-sig') as f:
        if list(csv.DictReader(f)):
            raise ValueError('Ya hay impactos registrados; se conservan y no se sobrescriben.')
    if output.exists() or clips.exists():
        raise ValueError('Ya existe una salida de segmentación; no se sobrescribe.')
    with (root / 'datos/metadatos/sesiones.csv').open(newline='') as f:
        sessions = list(csv.DictReader(f))
    inputs = []
    # Comprobar toda la entrada antes de crear archivos.
    for session in sessions:
        original = contained_path(raw, session['archivo'])
        wav = contained_path(decoded, str(Path(session['archivo']).with_suffix('.wav')))
        x, fs = sf.read(wav, dtype='float64')
        if sf.info(wav).subtype != 'PCM_24':
            raise ValueError('Se espera copia PCM de 24 bits verificada.')
        events, diagnostics = detect_candidates(x, fs)
        inputs.append((session, original, wav, x, fs, events, diagnostics))
    output.mkdir(parents=True)
    clips.mkdir(parents=True)
    (output / 'figuras').mkdir()
    os.environ.setdefault('MPLCONFIGDIR', str(output / '.matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    fig, axes = plt.subplots(len(inputs), 1, figsize=(13, 2.4 * len(inputs)), squeeze=False)
    records, file_records, metadata_rows = [], [], []
    sections = []
    for axis, data in zip(axes[:, 0], inputs):
        session, original, wav, x, fs, events, diagnostics = data
        sid = session['sesion_id']
        bucket = []
        step = max(1, len(x) // 3500)
        xx = x[:len(x)//step*step].reshape(-1, step)
        times = np.arange(len(xx)) * step / fs
        axis.vlines(times, xx.min(axis=1), xx.max(axis=1), lw=.5, color='#17657a')
        for number, event in enumerate(events, 1):
            iid = f'{sid}_G{number:02d}'
            start, end = event['inicio_muestra'], event['fin_muestra']
            path = clips / f'{iid}.wav'
            sf.write(path, x[start:end], fs, subtype='PCM_24')
            check, rate = sf.read(path)
            if rate != fs or not np.array_equal(check, x[start:end]):
                raise ValueError(f'El segmento {iid} no coincide con la copia fuente.')
            record = dict(impacto_id=iid, sesion_id=sid, objeto_id=session['objeto_id'],
                          archivo=session['archivo'], frecuencia_hz=fs, **event,
                          segmento=path.relative_to(root).as_posix(),
                          sha256_segmento=sha256_file(path),
                          aceptado='pendiente', revision='pendiente de escucha; límites preliminares')
            records.append(record)
            note = ' '.join(event['avisos']) or 'Candidato a golpe; confirmar por escucha.'
            metadata_rows.append(dict(impacto_id=iid, sesion_id=sid,
                inicio_muestra=start, fin_muestra=end, aceptado='pendiente',
                motivo_exclusion='', observaciones=note + ' Límites preliminares de contexto; no se ha calculado D90.'))
            color = '#cd7b0b' if event['avisos'] else '#31815c'
            axis.axvspan(start/fs, end/fs, alpha=.14, color=color)
            axis.text(event['pico_muestra']/fs, float(x.max())*1.10, str(number),
                      ha='center', fontsize=8, color=color)
            bucket.append(f"<tr data-id='{iid}'><td>{number}</td><td>{start/fs:.3f}–{end/fs:.3f} s</td>"
                f"<td><audio controls preload='none' src='../../{record['segmento']}'></audio></td>"
                f"<td>{html.escape(note)}</td><td><select aria-label='Estado {iid}'>"
                "<option value='pendiente'>Pendiente</option><option value='si'>Aceptar</option>"
                "<option value='no'>Excluir</option></select><input placeholder='Observación / motivo si excluyes' "
                f"aria-label='Observación {iid}'></td></tr>")
        axis.set_title(f"{session['archivo']} · {len(events)} eventos", loc='left', fontsize=11)
        axis.set_xlabel('Tiempo desde el inicio del archivo (s)')
        axis.set_ylabel('Amplitud')
        axis.set_xlim(0, len(x)/fs)
        axis.set_ylim(float(x.min())*1.25, float(x.max())*1.4)
        axis.grid(alpha=.15)
        # Figura individual idéntica a la del resumen, con sus límites y números.
        individual, ax = plt.subplots(figsize=(13, 2.8))
        ax.vlines(times, xx.min(axis=1), xx.max(axis=1), lw=.5, color='#17657a')
        for number, event in enumerate(events, 1):
            color = '#cd7b0b' if event['avisos'] else '#31815c'
            ax.axvspan(event['inicio_muestra']/fs, event['fin_muestra']/fs, color=color, alpha=.16)
            ax.text(event['pico_muestra']/fs, float(x.max())*1.1, str(number), ha='center', color=color)
        ax.set(xlabel='Tiempo (s)', ylabel='Amplitud', xlim=(0,len(x)/fs),
               ylim=(float(x.min())*1.25,float(x.max())*1.4))
        individual.tight_layout()
        individual.savefig(output/'figuras'/f'{sid}.png', dpi=120)
        plt.close(individual)
        file_records.append(dict(sesion_id=sid, archivo=session['archivo'],
            copia=wav.relative_to(root).as_posix(), sha256_original=sha256_file(original),
            sha256_copia=sha256_file(wav), muestras=len(x), frecuencia_hz=fs,
            eventos=len(events), **diagnostics))
        sections.append(f"<section><h2>{html.escape(session['archivo'])} · {len(events)} eventos</h2>"
            f"<img src='figuras/{sid}.png' alt='Límites y números de eventos'>"
            f"<p>Audio completo: <audio controls preload='none' src='../../{wav.relative_to(root).as_posix()}'></audio></p>"
            "<table><thead><tr><th>Evento</th><th>Intervalo</th><th>Escuchar</th><th>Revisión</th><th>Decisión</th></tr></thead>"
            f"<tbody>{''.join(bucket)}</tbody></table></section>")
    fig.tight_layout()
    fig.savefig(output/'resumen_visual.png', dpi=120)
    plt.close(fig)
    manifest = dict(estado='preliminar_pendiente_escucha', configuracion=SETTINGS,
        metodo='RMS mono por bloques; percentil 20 como fondo global; umbral máximo entre 6×fondo y 3.5% del máximo. Supresión de máximos a menos de 350 ms. Precontexto 50 ms; final tras 100 ms bajo máximo de 2.5×fondo y 1.5% del pico. No filtra ni normaliza. Puede omitir golpes débiles o próximos; revisar audio completo.',
        archivos=file_records, eventos=records)
    (output/'segmentacion.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    columns = SCHEMAS['impactos.csv']
    with metadata.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(metadata_rows)
    payload = json.dumps(metadata_rows, ensure_ascii=False).replace('<', '\\u003c')
    page = """<!doctype html><html lang="es"><meta charset="utf-8"><title>Revisión de golpes</title>
<style>body{font:16px system-ui;max-width:1250px;margin:32px auto;padding:0 24px;color:#20343c}h1,h2{color:#15566a}section{margin:40px 0}img{width:100%}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #ddd;padding:10px;vertical-align:top}audio{width:230px}input{display:block;margin-top:8px;width:220px}select,button,input{font:inherit;padding:6px}.notice{padding:18px;background:#fff2d9}button{cursor:pointer}td:nth-child(4){max-width:300px}</style>
<h1>Revisión de golpes del piloto</h1>
<p class="notice">42 eventos candidatos de 8 objetos. Todos están pendientes de escucha. Los números corresponden a los segmentos de cada grabación; naranja señala avisos. Las ventanas incluyen contexto y todavía no sirven para calcular D90 sin acordar el tratamiento del fondo.</p>
<p>Escucha también el audio completo para detectar golpes omitidos o dobles. Puedes aceptar o excluir eventos y anotar el motivo. Las decisiones se guardan en este navegador; descarga el CSV para conservarlas. El archivo de metadatos del proyecto permanece pendiente hasta incorporar esa revisión.</p>
<button id="export">Descargar revisión CSV</button><span id="state"></span>
""" + ''.join(sections) + '<script>const rows=' + payload + ";\n" + """
const key='revision-golpes-yiyi-v1';
let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){}
function status(){const n=rows.filter(r=>r.aceptado!=='pendiente').length;document.querySelector('#state').textContent=` ${n} de ${rows.length} revisados`;}
document.querySelectorAll('tr[data-id]').forEach(tr=>{
 const row=rows.find(r=>r.impacto_id===tr.dataset.id),select=tr.querySelector('select'),input=tr.querySelector('input');
 if(saved[row.impacto_id])Object.assign(row,saved[row.impacto_id]);
 select.value=row.aceptado;input.value=row.motivo_exclusion||row.nota_revision||'';
 function update(){row.aceptado=select.value;row.motivo_exclusion=select.value==='no'?input.value:'';row.nota_revision=input.value;saved[row.impacto_id]={aceptado:row.aceptado,motivo_exclusion:row.motivo_exclusion,nota_revision:input.value};try{localStorage.setItem(key,JSON.stringify(saved));}catch(e){document.querySelector('#state').textContent='No se pudo guardar localmente: descarga el CSV.';return;}status();}
 select.onchange=update;input.oninput=update;
});status();
document.querySelector('#export').onclick=()=>{
 if(rows.some(r=>r.aceptado==='no'&&!r.motivo_exclusion.trim())){alert('Escribe el motivo de cada exclusión antes de descargar.');return;}
 const cols=['impacto_id','sesion_id','inicio_muestra','fin_muestra','aceptado','motivo_exclusion','observaciones'];
 const esc=v=>'"'+String(v??'').replaceAll('"','""')+'"';
 const csv=[cols.join(','),...rows.map(r=>cols.map(c=>esc(c==='observaciones'?r.observaciones+(r.nota_revision?' Revisión: '+r.nota_revision:''):r[c])).join(','))].join('\\r\\n');
 const url=URL.createObjectURL(new Blob(['\\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='impactos_revisados.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};</script></html>"""
    page = page.replace('42 eventos candidatos de 8 objetos.',
                        f'{len(records)} eventos candidatos de {len({s[0]["objeto_id"] for s in inputs})} objetos.')
    (output/'revision.html').write_text(page, encoding='utf-8')
    return manifest
