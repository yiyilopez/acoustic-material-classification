"""El ejemplo publicado reproduce un resultado real del método piloto."""

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from acustica_materiales.features import periodogram, spectral_moments, duration90


def test_real_audio_example_matches_recorded_features():
    folder=Path(__file__).resolve().parents[1]/'examples/botella_vidrio'
    metadata=json.loads((folder/'manifest.json').read_text())
    audio=folder/'botella_golpe01.wav'
    assert hashlib.sha256(audio.read_bytes()).hexdigest()==metadata['sha256_recorte']
    x,fs=sf.read(audio)
    assert fs==48000 and x.ndim==1
    a,b=metadata['ventanas_relativas_recorte']['espectral']
    f,p=periodogram(x[a:b],fs,metadata['configuracion'])
    band=(f>=100)&(f<=20000)
    result=spectral_moments(f[band],p[band])
    a,b=metadata['ventanas_relativas_recorte']['fondo']
    mean=x[a:b].mean();noise=np.mean((x[a:b]-mean)**2)
    a,b=metadata['ventanas_relativas_recorte']['temporal']
    result.update(duration90(x[a:b]-mean,fs,noise))
    for key,expected in metadata['esperados'].items():
        assert np.isclose(result[key],expected,rtol=1e-10,atol=1e-12),key
