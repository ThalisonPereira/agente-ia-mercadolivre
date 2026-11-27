"""
Pacote de configuração. Importado antes de qualquer integração (todas passam por config.settings), então é o lugar certo
para ligar a confiança no repositório de certificados do Windows.

No Windows, antivírus com varredura de HTTPS (ex.: Avast Web/Mail Shield, que reassina os certificados com uma raiz própria) fazem
o Python recusar as conexões ("CERTIFICATE_VERIFY_FAILED") porque o `certifi` não conhece essa raiz, enquanto o navegador e o curl
funcionam. O `truststore` faz o Python usar o repositório do próprio sistema; a verificação de TLS continua LIGADA. Fora do Windows
(ex.: GitHub Actions) nada muda.
"""

import sys

if sys.platform == "win32":
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:  # sem o pacote instalado o comportamento é o de antes (certifi)
        pass
