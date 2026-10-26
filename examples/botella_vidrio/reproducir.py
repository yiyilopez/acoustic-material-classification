"""Reproduce el tutorial con un recorte real, sin alterar el audio publicado."""

import csv
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import soundfile as sf

from acustica_materiales.features import duration90, periodogram, spectral_moments

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FIGURES = ROOT / 'docs/tutorial/figuras'


def reproduce():
    metadata = json.loads((HERE/'manifest.json').read_text())
    audio = HERE/'botella_golpe01.wav'
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == metadata['sha256_recorte']
    x, fs = sf.read(audio, dtype='float64')
    assert fs == metadata['fs_hz'] and x.ndim == 1
    w = metadata['ventanas_relativas_recorte']
    ns, ne = w['fondo']
    start, end = w['temporal']
    ss, se = w['espectral']
    background = x[ns:ne]
    mean = float(background.mean())
    noise = float(np.mean((background-mean)**2))
    f, power = periodogram(x[ss:se], fs, metadata['configuracion'])
    mask = (f >= 100) & (f <= 20000)
    frequency, p = f[mask], power[mask]
    descriptors = spectral_moments(frequency, p)
    y = x[start:end]-mean
    temporal = duration90(y, fs, noise)
    result = descriptors | temporal
    for key in ['fp_hz','centroide_hz','ancho_hz','ancho_relativo','d90_s','t05_s','t95_s']:
        assert np.isclose(result[key], metadata['esperados'][key], rtol=1e-10, atol=1e-12), key
    block = round(fs*.001)
    starts = np.arange(0, len(y), block)
    counts = np.minimum(block, len(y)-starts)
    energy_raw = np.add.reduceat(y*y, starts)
    energy = np.maximum(energy_raw-counts*noise, 0)
    cumulative = np.cumsum(energy)/energy.sum()
    q = p/p.sum()
    f_alt,p_alt=periodogram(x[ss+round(.01*fs):se+round(.01*fs)],fs,metadata['configuracion'])
    m_alt=(f_alt>=100)&(f_alt<=20000)
    alternative=spectral_moments(f_alt[m_alt],p_alt[m_alt])
    result.update(fs_hz=fs,ventana_espectral_muestras=se-ss,
        separacion_bins_hz=fs/(se-ss),potencia_fondo=noise,media_fondo=mean,
        duracion_ventana_temporal_s=(end-start)/fs,alternativa_desplazada_10ms=alternative)
    (HERE/'resultados.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    with (HERE/'espectro.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['frecuencia_hz','densidad_potencia_digital','peso_normalizado','contribucion_centroide_hz','contribucion_varianza_hz2'])
        writer.writerows(zip(frequency,p,q,frequency*q,(frequency-descriptors['centroide_hz'])**2*q))
    with (HERE/'energia.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['inicio_ms','fin_ms','suma_cuadrados','fondo_descontado','energia_corregida','fraccion_acumulada'])
        writer.writerows(zip(starts/fs*1000,(starts+counts)/fs*1000,energy_raw,counts*noise,energy,cumulative))
    FIGURES.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,
        'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold',
        'figure.facecolor':'white','axes.labelcolor':'#24343b','text.color':'#24343b'})
    blue, gold, green = '#22617b', '#bb7520', '#347b65'
    t=(np.arange(len(x))-start)/fs*1000
    c=descriptors['centroide_hz']; b=descriptors['ancho_hz']; peak=descriptors['fp_hz']
    low,high=temporal['t05_s']*1000,temporal['t95_s']*1000

    def finish(fig,name):
        fig.tight_layout()
        fig.savefig(FIGURES/name,dpi=160,bbox_inches='tight')
        plt.close(fig)

    fig,ax=plt.subplots(2,1,figsize=(11,6.5))
    ax[0].plot(t,x,color=blue,lw=.5)
    ax[0].axvspan((ns-start)/fs*1000,(ne-start)/fs*1000,color='#c8d4da',alpha=.75,label='Fondo: 300 ms')
    ax[0].axvspan(0,(end-start)/fs*1000,color=green,alpha=.12,label='Temporal: 506 ms')
    ax[0].axvspan(0,100,color=gold,alpha=.25,label='Espectral: 100 ms')
    ax[0].set(title='1 · Del audio real a dos ventanas de análisis',xlabel='Tiempo desde el inicio ajustado (ms)',ylabel='Amplitud digital')
    ax[0].legend(loc='upper right',fontsize=9)
    ax[1].plot(np.arange(se-ss)/fs*1000,x[ss:se],color=blue,lw=.6)
    ax[1].set(title='Detalle: las 4800 muestras de la ventana espectral',xlabel='Tiempo (ms)',ylabel='Amplitud digital',xlim=(0,100))
    finish(fig,'01_ventanas.png')

    fig,ax=plt.subplots(figsize=(11,4.5))
    relative=10*np.log10(np.maximum(p/p.max(),1e-10))
    ax.plot(frequency/1000,relative,color=blue,lw=.8)
    ax.axvline(peak/1000,color=gold,linestyle='--',lw=1.3)
    ax.annotate(f'fₚ = {peak:.0f} Hz\nMáximo de potencia',xy=(peak/1000,0),xytext=(6,-4),
        arrowprops={'arrowstyle':'->','color':gold},color=gold)
    ax.set(title='2 · Frecuencia prominente: buscamos el máximo del espectro',
        xlabel='Frecuencia (kHz)',ylabel='Potencia relativa al máximo (dB)',xlim=(.1,20),ylim=(-70,4))
    ax.grid(alpha=.15)
    finish(fig,'02_frecuencia_prominente.png')

    # Las barras agrupan frecuencias para explicar los pesos; el cálculo exacto usa bins de 10 Hz.
    edges=np.arange(0,21000,1000)
    weights=np.histogram(frequency,bins=edges,weights=q)[0]*100
    centers=(edges[:-1]+edges[1:])/2000
    fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True)
    for axis in axes:
        axis.bar(centers,weights,width=.88,color=blue,alpha=.85)
        axis.axvline(c/1000,color=gold,linestyle='--',lw=1.5)
        axis.set(ylabel='Potencia en cada banda (%)',xlim=(0,20))
        axis.grid(axis='y',alpha=.15)
    axes[0].set_title(f'3 · Centroide: el promedio ponderado es C = {c:.2f} Hz')
    axes[0].annotate('C: centro de los pesos\n(no es el máximo)',xy=(c/1000,max(weights)*.8),
        xytext=(7,max(weights)*.85),arrowprops={'arrowstyle':'->','color':gold},color=gold)
    axes[1].axvspan((c-b)/1000,(c+b)/1000,color=gold,alpha=.15)
    axes[1].annotate('',xy=((c-b)/1000,max(weights)*.72),xytext=((c+b)/1000,max(weights)*.72),
        arrowprops={'arrowstyle':'<->','color':gold})
    axes[1].text(7,max(weights)*.60,f'B = {b:.2f} Hz\nB/C = {b/c:.4f}',color=gold,fontsize=12)
    axes[1].set(title='4 · Ancho relativo: dispersión alrededor de C, dividida por C',xlabel='Frecuencia (kHz)')
    fig.text(.12,.005,'Las barras agrupan bandas de 1 kHz solo para visualizar. C y B se calculan con frecuencias cada 10 Hz.\nLa zona C ± B no es un intervalo de confianza ni contiene necesariamente el 68 % de la potencia.',fontsize=9)
    fig.tight_layout(rect=(0,.065,1,1))
    fig.savefig(FIGURES/'03_centroide_ancho.png',dpi=160,bbox_inches='tight');plt.close(fig)

    fig,axes=plt.subplots(2,1,figsize=(11,7))
    for axis in axes:
        axis.plot(np.r_[0,(starts+counts)/fs*1000],np.r_[0,cumulative*100],color=green,lw=1.5)
        axis.axhline(5,color='#78858b',linestyle=':',lw=1)
        axis.axhline(95,color='#78858b',linestyle=':',lw=1)
        axis.axvspan(low,high,color=gold,alpha=.15)
        axis.plot([low,high],[5,95],'o',color=gold)
        axis.set(xlabel='Tiempo desde el inicio ajustado (ms)',ylabel='Energía acumulada (%)',ylim=(0,103))
        axis.grid(alpha=.12)
    axes[0].set(title='5 · D₉₀: del 5 % al 95 % de energía corregida',xlim=(0,(end-start)/fs*1000))
    axes[1].set(title=f'Detalle: D₉₀ = t₉₅ − t₀₅ ≈ {high-low:.3f} ms',xlim=(0,120))
    axes[1].annotate(f't₀₅ = {low:.3f} ms',xy=(low,5),xytext=(20,17),arrowprops={'arrowstyle':'->','color':gold})
    axes[1].annotate(f't₉₅ = {high:.3f} ms',xy=(high,95),xytext=(78,75),arrowprops={'arrowstyle':'->','color':gold})
    finish(fig,'04_duracion_energetica.png')

    fig,axes=plt.subplots(2,2,figsize=(12,7.6))
    axes[0,0].plot(np.arange(se-ss)/fs*1000,x[ss:se],color=blue,lw=.6)
    axes[0,0].set(title='Audio · un golpe de botella',xlabel='Tiempo (ms)',ylabel='Amplitud digital',xlim=(0,100))
    axes[0,1].plot(frequency/1000,relative,color=blue,lw=.65)
    axes[0,1].axvline(peak/1000,color=gold,linestyle='--')
    axes[0,1].set(title=f'fₚ = {peak:.0f} Hz',xlabel='Frecuencia (kHz)',ylabel='Potencia relativa (dB)',xlim=(.1,20),ylim=(-65,3))
    axes[1,0].bar(centers,weights,width=.88,color=blue)
    axes[1,0].axvline(c/1000,color=gold,linestyle='--')
    axes[1,0].axvspan((c-b)/1000,(c+b)/1000,color=gold,alpha=.15)
    axes[1,0].set(title=f'C = {c:.1f} Hz · B/C = {b/c:.4f}',xlabel='Frecuencia (kHz)',ylabel='Potencia por banda (%)',xlim=(0,20))
    axes[1,1].plot(np.r_[0,(starts+counts)/fs*1000],np.r_[0,cumulative*100],color=green)
    axes[1,1].axvspan(low,high,color=gold,alpha=.2)
    axes[1,1].set(title=f'D₉₀ = {high-low:.3f} ms',xlabel='Tiempo (ms)',ylabel='Energía acumulada (%)',xlim=(0,120),ylim=(0,103))
    fig.suptitle('De un golpe real a cuatro descriptores acústicos',fontsize=17)
    finish(fig,'00_resumen.png')
    return result


if __name__=='__main__':
    values=reproduce()
    print(json.dumps({k:values[k] for k in ['fp_hz','centroide_hz','ancho_hz','ancho_relativo','t05_s','t95_s','d90_s']},indent=2))
