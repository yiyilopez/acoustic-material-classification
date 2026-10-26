"""Ventanas y descriptores del piloto, con trazabilidad y sensibilidad al fondo."""

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

from .inspection import sha256_file
from .paths import check_output_folder, contained_path


DEFAULTS = dict(banda_hz=[100, 20000], ventana_espectral_ms=100,
    contexto_pre_ms=2, bloque_energia_ms=1, suavizado_final_ms=5,
    persistencia_final_ms=30, factor_potencia_final=2,
    max_cola_ms=750, fondo_inicio_antes_pico_ms=350,
    fondo_fin_antes_pico_ms=50, rampa_inicial_ms=1, rampa_final_ms=10)


def spectral_moments(frequency, power):
    f, p = np.asarray(frequency), np.asarray(power)
    if f.shape != p.shape or np.any(p < 0) or not np.isfinite(p).all():
        raise ValueError('Espectro no válido.')
    total = float(p.sum())
    if total <= 0:
        return dict(fp_hz=None, centroide_hz=None, ancho_hz=None, ancho_relativo=None)
    centroid = float(np.dot(f, p) / total)
    bandwidth = float(np.sqrt(np.dot((f - centroid)**2, p) / total))
    return dict(fp_hz=float(f[np.argmax(p)]), centroide_hz=centroid,
                ancho_hz=bandwidth, ancho_relativo=bandwidth / centroid if centroid > 0 else None)


def periodogram(x, fs, settings=DEFAULTS):
    y = np.asarray(x, dtype=float)
    if len(y) < 3 or not np.isfinite(y).all():
        raise ValueError('Ventana espectral vacía o inválida.')
    w = np.ones(len(y))
    a = min(round(fs * settings['rampa_inicial_ms']/1000), len(y)//2)
    b = min(round(fs * settings['rampa_final_ms']/1000), len(y)//2)
    if a:
        w[:a] = np.sin(np.linspace(0, np.pi/2, a))**2
    if b:
        w[-b:] = np.cos(np.linspace(0, np.pi/2, b))**2
    power = abs(np.fft.rfft((y - y.mean()) * w))**2 / (fs * np.dot(w, w))
    if len(y) % 2 == 0:
        power[1:-1] *= 2
    else:
        power[1:] *= 2
    frequency = np.fft.rfftfreq(len(y), 1/fs)
    return frequency, power


def duration90(x, fs, background_power=0, block_ms=1):
    """D90 de energía por bloques, descontando fondo antes de integrar.

    Cada bloque aporta max(suma(x²)-N*P_fondo,0). Interpolación uniforme
    dentro del bloque; resolución efectiva = block_ms, sin ponderación FFT.
    """
    x = np.asarray(x, dtype=float)
    if background_power < 0 or not np.isfinite(x).all():
        raise ValueError('Señal o fondo inválido.')
    block = max(1, round(fs * block_ms / 1000))
    starts = np.arange(0, len(x), block)
    if not len(starts):
        return dict(d90_s=None, t05_s=None, t95_s=None, energia_corregida=0)
    counts = np.minimum(block, len(x)-starts)
    energy = np.maximum(np.add.reduceat(x*x, starts) - counts*background_power, 0)
    total = float(energy.sum())
    if total <= 0:
        return dict(d90_s=None, t05_s=None, t95_s=None, energia_corregida=total)
    cumulative = np.cumsum(energy)
    def quantile(q):
        k = int(np.searchsorted(cumulative, q*total))
        previous = cumulative[k-1] if k else 0
        fraction = (q*total-previous)/energy[k]
        return float((starts[k]+fraction*counts[k])/fs)
    low, high = quantile(.05), quantile(.95)
    return dict(d90_s=high-low, t05_s=low, t95_s=high, energia_corregida=total)


def refine_window(x, fs, event, next_start, settings=DEFAULTS):
    peak = event['pico_muestra']
    ns = peak-round(fs*settings['fondo_inicio_antes_pico_ms']/1000)
    ne = peak-round(fs*settings['fondo_fin_antes_pico_ms']/1000)
    if ns < 0 or ne <= ns:
        raise ValueError('No hay suficiente fondo anterior al golpe.')
    baseline = x[ns:ne]
    mean = float(baseline.mean())
    noise = float(np.mean((baseline-mean)**2))
    block = max(1, round(fs*settings['bloque_energia_ms']/1000))
    count = len(x)//block
    env = np.mean((x[:count*block].reshape(-1, block)-mean)**2, axis=1)
    kpeak = min(peak//block, count-1)
    # Frente: última racha de 5 ms a nivel de fondo antes del máximo RMS.
    quiet = 0
    onset = max(0, kpeak-round(.12*fs/block))
    for k in range(kpeak-1, onset-1, -1):
        quiet = quiet+1 if env[k] <= 9*noise else 0
        if quiet >= 5:
            onset = k+quiet
            break
    start = max(0, onset*block-round(fs*settings['contexto_pre_ms']/1000))
    limit = min(len(x), start+round(fs*settings['max_cola_ms']/1000), next_start)
    if limit <= peak:
        raise ValueError('La ventana no contiene el máximo detectado.')
    smooth_n = max(1, round(settings['suavizado_final_ms'] / settings['bloque_energia_ms']))
    # Promedio hacia delante; la persistencia cubre 30 ms completos.
    smooth = np.convolve(env, np.ones(smooth_n)/smooth_n, mode='valid')
    hold = max(1, round(settings['persistencia_final_ms']/settings['bloque_energia_ms']))
    end, quiet, returned = limit, 0, False
    for k in range(kpeak+max(1, round(.015*fs/block)), min(len(smooth), limit//block-smooth_n)):
        quiet = quiet+1 if smooth[k] <= settings['factor_potencia_final']*noise else 0
        if quiet >= hold:
            end = min(limit, (k+smooth_n)*block)
            returned = True
            break
    return dict(inicio_muestra=start, fin_muestra=end, frente_muestra=onset*block,
                fondo_inicio_muestra=ns, fondo_fin_muestra=ne, media_fondo=mean,
                potencia_fondo=noise, retorno_fondo=returned, limite_muestra=limit)


def _csv(path, rows):
    if not rows:
        raise ValueError('No hay filas para exportar.')
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def extract_pilot(root: Path):
    output = root/'resultados/descriptores_piloto'
    features_dir = root/'datos/caracteristicas/piloto_v1'
    clips = root/'datos/procesados/ventanas_piloto_v1'
    for folder in (output, features_dir, clips):
        check_output_folder(root/'datos/originales', folder)
        if folder.exists():
            raise ValueError(f'La salida ya existe, no se sobrescribe: {folder}')
    settings = DEFAULTS | json.loads((root/'config.json').read_text()).get('extraccion_piloto_v1', {})
    segmentation = json.loads((root/'resultados/segmentacion_piloto/segmentacion.json').read_text())
    events = {e['impacto_id']: e for e in segmentation['eventos']}
    with (root/'datos/metadatos/impactos.csv').open(newline='') as f:
        reviewed = list(csv.DictReader(f))
    with (root/'datos/metadatos/objetos.csv').open(newline='') as f:
        objects = {o['objeto_id']: o for o in csv.DictReader(f)}
    assert len(reviewed)==len(events) and len({r['impacto_id'] for r in reviewed})==len(events)
    assert set(events)=={r['impacto_id'] for r in reviewed}
    if any(r['aceptado']=='pendiente' for r in reviewed):
        raise ValueError('Quedan impactos pendientes de revisión.')
    source_hashes = {record['archivo']: record['sha256_original'] for record in segmentation['archivos']}
    for filename, digest in source_hashes.items():
        if sha256_file(contained_path(root/'datos/originales', filename)) != digest:
            raise ValueError('Cambió un original desde la segmentación.')
    for folder in (output, features_dir, clips):
        folder.mkdir(parents=True)
    (output/'figuras').mkdir()
    os.environ.setdefault('MPLCONFIGDIR', str(root/'resultados/segmentacion_piloto/.matplotlib'))
    from matplotlib import pyplot as plt
    values, audit, plots = [], [], {}
    for record in segmentation['archivos']:
        sid = record['sesion_id']
        wav = contained_path(root, record['copia'])
        if sha256_file(wav) != record['sha256_copia']:
            raise ValueError('Cambió una copia decodificada.')
        x, fs = sf.read(wav)
        if x.ndim != 1 or fs/2 < settings['banda_hz'][1]:
            raise ValueError('Se requiere audio mono con banda común disponible.')
        session_events = sorted([e for e in events.values() if e['sesion_id']==sid], key=lambda e:e['pico_muestra'])
        accepted = [r for r in reviewed if r['sesion_id']==sid and r['aceptado']=='si']
        fig, axes = plt.subplots(len(accepted), 3, figsize=(14, 2.7*len(accepted)), squeeze=False)
        for row, axes_row in zip(accepted, axes):
            iid = row['impacto_id']
            e = events[iid]
            if any(int(row[k]) != e[k] for k in ('inicio_muestra','fin_muestra')):
                raise ValueError('La revisión modificó límites; comprobar antes de continuar.')
            j = session_events.index(e)
            following = session_events[j+1]['inicio_muestra'] if j+1<len(session_events) else len(x)
            window = refine_window(x, fs, e, following, settings)
            start, end = window['inicio_muestra'], window['fin_muestra']
            ns, ne = window['fondo_inicio_muestra'], window['fondo_fin_muestra']
            y = x[start:end]-window['media_fondo']
            n = round(fs*settings['ventana_espectral_ms']/1000)
            if start+n > following or start+n > len(x):
                raise ValueError('No hay 100 ms sin otro evento.')
            spectral_y = x[start:start+n]
            f, p = periodogram(spectral_y, fs, settings)
            band = (f>=settings['banda_hz'][0]) & (f<=settings['banda_hz'][1])
            descriptors = spectral_moments(f[band], p[band])
            temporal = duration90(y, fs, window['potencia_fondo'])
            raw_duration = duration90(y, fs)
            # Fondo espectral: promedio de tres ventanas contiguas con igual taper.
            baseline = x[ns:ne]
            ps_noise = np.mean([periodogram(baseline[a:a+n], fs, settings)[1]
                               for a in range(0,len(baseline)-n+1,n)], axis=0)
            corrected = spectral_moments(f[band], np.maximum(p[band]-ps_noise[band],0))
            variations = [duration90(y,fs,window['potencia_fondo']*factor)['d90_s'] for factor in (.5,1.5)]
            ext_end = min(window['limite_muestra'],end+round(.05*fs))
            extended = duration90(x[start:ext_end]-window['media_fondo'],fs,window['potencia_fondo'])['d90_s']
            alternatives = {}
            for ms in (80,120):
                nn=round(ms*fs/1000)
                if start+nn<=following and start+nn<=len(x):
                    ff,pp=periodogram(x[start:start+nn],fs,settings)
                    bb=(ff>=settings['banda_hz'][0])&(ff<=settings['banda_hz'][1])
                    alternatives[str(ms)]=spectral_moments(ff[bb],pp[bb])
            # Métrica de diagnóstico: energía media observada / energía de fondo.
            snr = float(10*np.log10(max(np.mean(y*y),np.finfo(float).tiny)/max(window['potencia_fondo'],np.finfo(float).tiny)))
            warnings=[]
            if not window['retorno_fondo']:
                warnings.append('no_retorna_al_fondo_antes_del_limite')
            if snr<10:
                warnings.append('baja_relacion_energia_fondo')
            d = temporal['d90_s']
            sensitivity = max([abs(v-d)/d for v in variations+[extended] if v is not None],default=0) if d else None
            if sensitivity is not None and sensitivity>.20:
                warnings.append('d90_sensible_a_fondo_o_final')
            cs = descriptors['centroide_hz']
            spectral_sensitivity = max([abs(v['centroide_hz']-cs)/cs for v in alternatives.values()])
            peak_sensitivity = max(abs(v['fp_hz']-descriptors['fp_hz'])/descriptors['fp_hz'] for v in alternatives.values())
            if spectral_sensitivity>.20:
                warnings.append('centroide_sensible_a_ventana')
            if peak_sensitivity>.20:
                warnings.append('frecuencia_prominente_sensible_a_ventana')
            if d is None:
                warnings.append('sin_energia_corregida')
            valid_duration = window['retorno_fondo'] and d is not None
            if float(np.max(np.abs(x[start:max(end,start+n)])))>=.999:
                warnings.append('muestras_cerca_limite_digital')
            clip=clips/f'{iid}.wav'
            sf.write(clip,x[start:end],fs,subtype='PCM_24')
            samples,rate=sf.read(clip)
            if rate!=fs or not np.array_equal(samples,x[start:end]):
                raise ValueError('El segmento exportado no coincide con la fuente.')
            value=dict(impacto_id=iid,sesion_id=sid,objeto_id=e['objeto_id'],material=objects[e['objeto_id']]['material'],
                fs_hz=fs,inicio_muestra=start,fin_muestra=end,
                espectro_inicio_muestra=start,espectro_fin_muestra=start+n,
                fondo_inicio_muestra=ns,fondo_fin_muestra=ne,**descriptors,
                d90_s=d if valid_duration else None,
                t05_s=temporal['t05_s'] if valid_duration else None,
                t95_s=temporal['t95_s'] if valid_duration else None,
                d90_provisional_ventana_s=d, d90_estimable=valid_duration,
                duracion_ventana_s=(end-start)/fs,fondo_rms=float(np.sqrt(window['potencia_fondo'])),
                relacion_energia_fondo_db=snr,d90_sin_restar_fondo_s=raw_duration['d90_s'],
                sensibilidad_d90_relativa=sensitivity,sensibilidad_centroide_relativa=spectral_sensitivity,
                sensibilidad_fp_relativa=peak_sensitivity,
                estado='revisar_sensibilidad' if warnings else 'calculado',avisos=';'.join(warnings))
            values.append(value)
            audit.append(dict(impacto_id=iid,**window,espectro_n_muestras=n,
                d90_fondo_mitad_s=variations[0],d90_fondo_1_5_s=variations[1],d90_final_mas_50ms_s=extended,
                espectro_80_120_ms=alternatives,espectro_con_resta_fondo=corrected,
                segmento=clip.relative_to(root).as_posix(),sha256_segmento=sha256_file(clip)))
            # Onda y ventanas respecto al pico detectado; fondo en panel aparte.
            ax,sp,en=axes_row
            lo=max(ns,start-round(.03*fs));hi=min(len(x),max(end,start+n)+round(.03*fs))
            stride=max(1,(hi-lo)//2500)
            ax.plot((np.arange(lo,hi,stride)-start)/fs,x[lo:hi:stride],lw=.45,color='#1c6174')
            ax.axvspan(0,(end-start)/fs,color='#258267',alpha=.15,label='Temporal')
            ax.axvspan(0,n/fs,color='#cd8a20',alpha=.16,label='Espectral')
            ax.set(title=iid+(' · revisar' if warnings else ''),xlabel='Tiempo desde inicio ajustado (s)',ylabel='Amplitud')
            sp.plot(f[band],10*np.log10(np.maximum(p[band],1e-20)),lw=.6,color='#1c6174')
            sp.plot(f[band],10*np.log10(np.maximum(ps_noise[band],1e-20)),lw=.5,color='#aaaaaa',label='Fondo')
            sp.axvline(descriptors['fp_hz'],color='#cd8a20',lw=.8)
            sp.set(xlabel='Frecuencia (Hz)',ylabel='PSD (dB re 1 unidad²/Hz)',xlim=(100,20000))
            block=round(fs*.001);starts=np.arange(0,len(y),block)
            energy=np.maximum(np.add.reduceat(y*y,starts)-np.minimum(block,len(y)-starts)*window['potencia_fondo'],0)
            if energy.sum()>0:
                en.plot((starts+np.minimum(block,len(y)-starts))/fs,np.cumsum(energy)/energy.sum(),color='#258267',lw=1)
            if d:
                en.axvline(temporal['t05_s'],color='#cd8a20',lw=.8)
                en.axvline(temporal['t95_s'],color='#cd8a20',lw=.8)
            if not valid_duration:
                en.set_title('D90 no estimable: cola sin aislar',fontsize=9,color='#9c4b0a')
            en.set(xlabel='Tiempo desde inicio ajustado (s)',ylabel='Energía acumulada / total',ylim=(0,1.05))
        fig.tight_layout()
        name=f'figuras/{sid}.png'
        fig.savefig(output/name,dpi=130)
        plt.close(fig)
        plots[sid]=name
    summary=[]
    for oid in sorted({v['objeto_id'] for v in values}):
        group=[v for v in values if v['objeto_id']==oid]
        item=dict(objeto_id=oid,material=objects[oid]['material'],descripcion=objects[oid]['descripcion'],
            golpes_aceptados=len(group),golpes_con_avisos=sum(bool(v['avisos']) for v in group))
        for key in ('fp_hz','centroide_hz','ancho_relativo','d90_s'):
            a=[v[key] for v in group if v[key] is not None]
            item[key+'_n']=len(a)
            item[key+'_mediana']=float(np.median(a)) if a else None
            item[key+'_q25']=float(np.quantile(a,.25)) if a else None
            item[key+'_q75']=float(np.quantile(a,.75)) if a else None
        summary.append(item)
    _csv(features_dir/'por_golpe.csv',values)
    _csv(features_dir/'por_objeto.csv',summary)
    _csv(features_dir/'ventanas.csv',[{k:v[k] for k in ('impacto_id','sesion_id','objeto_id','fs_hz','inicio_muestra','fin_muestra','espectro_inicio_muestra','espectro_fin_muestra','fondo_inicio_muestra','fondo_fin_muestra')} for v in values])
    result=dict(generado_utc=datetime.now(timezone.utc).isoformat(),version_metodo='piloto_v1',
        configuracion=settings,sha256_revision=sha256_file(root/'datos/metadatos/impactos.csv'),
        originales=source_hashes,golpes_aceptados=len(values),excluidos=sum(r['aceptado']=='no' for r in reviewed),
        ventanas=audit,resultados=values,por_objeto=summary,figuras=plots)
    (output/'calculo.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    for filename,digest in source_hashes.items():
        if sha256_file(contained_path(root/'datos/originales',filename))!=digest:
            raise ValueError('Se alteró un original.')
    return result
