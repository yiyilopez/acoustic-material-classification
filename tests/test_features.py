import numpy as np
import pytest

from acustica_materiales.features import duration90, periodogram, spectral_moments, refine_window


def test_known_power_moments_and_silence():
    result=spectral_moments([1000,3000], [3,1])
    assert result['fp_hz']==1000
    assert result['centroide_hz']==1500
    assert result['ancho_hz']==pytest.approx(np.sqrt(750000))
    assert result['ancho_relativo']==pytest.approx(np.sqrt(750000)/1500)
    assert spectral_moments([1,2],[0,0])['centroide_hz'] is None
    assert duration90(np.zeros(1000),1000)['d90_s'] is None


def test_d90_constant_energy_and_gain_invariance():
    fs=10000
    x=np.ones(fs)
    assert duration90(x,fs)['d90_s']==pytest.approx(.9,abs=1/fs)
    assert duration90(x,fs,.2)['d90_s']==pytest.approx(duration90(3*x,fs,1.8)['d90_s'])


def test_exponential_energy_duration_and_invariance():
    fs=48000
    tau=.04
    t=np.arange(fs//2)/fs
    x=np.exp(-t/tau)
    expected=tau/2*np.log(19)
    assert duration90(x,fs)['d90_s']==pytest.approx(expected,abs=.001)
    assert duration90(.2*x,fs)['d90_s']==pytest.approx(duration90(x,fs)['d90_s'])


def test_sinusoid_frequency_and_parseval_scaling():
    fs=48000
    x=np.sin(2*np.pi*1000*np.arange(4800)/fs)
    f,p=periodogram(x,fs)
    r=spectral_moments(f,p)
    assert r['fp_hz']==1000
    assert r['centroide_hz']==pytest.approx(1000,abs=10)
    assert p.sum()*(fs/len(x))==pytest.approx(.5,abs=.002)
    f,q=periodogram(x*.1,fs)
    assert spectral_moments(f,q)['ancho_relativo']==pytest.approx(r['ancho_relativo'])


def test_noise_subtraction_is_before_rectification_of_block_energy():
    assert duration90(np.ones(1000),1000,1)['d90_s'] is None
    with pytest.raises(ValueError):
        duration90(np.ones(1000),1000,-1)


def test_refined_window_returns_to_local_background_before_later_noise():
    fs=10000
    rng=np.random.default_rng(7)
    x=rng.normal(0,.001,20000)
    t=np.arange(5000)/fs
    x[8000:13000]+=.3*np.exp(-t/.025)*np.sin(2*np.pi*1500*t)
    x[14000:]+=rng.normal(0,.03,6000)
    result=refine_window(x,fs,{'pico_muestra':8020},15000)
    assert result['inicio_muestra']<8000
    assert 8300<result['fin_muestra']<14000
    assert result['retorno_fondo']
    assert result['fondo_fin_muestra']<result['inicio_muestra']
