# =====================================================================
# Sidecar WindNinja — campo de vento ajustado ao relevo
# =====================================================================
# Base conda-forge e não python:3.12-slim como os outros serviços: o
# WindNinja não existe em pip nem em apt, só em conda-forge. É essa a
# razão de ser deste container separado — ver WINDNINJA_PLAN.md.
#
# Sem volume e sem credenciais: recebe a janela do DEM no pedido HTTP.
# No Railway "each service can only have a single volume" e os volumes
# não se partilham, portanto ler o landscape do volume da API não é
# possível.
# =====================================================================
FROM condaforge/miniforge3:24.9.2-0

WORKDIR /app

# `mamba create` num ambiente NOVO, e não `mamba install` na base.
#
# Não é preferência de estilo: instalar na base da imagem deixa o solver
# preso às versões que ela já traz, e o resultado foi um ambiente
# inconsistente — libgdal.so.37 a pedir `sqlite3_total_changes64`
# (SQLite >= 3.37) contra a libsqlite antiga da base, e o `import
# rasterio` a rebentar só em runtime, depois de o build passar. Num
# ambiente novo o solver resolve de raiz e traz libsqlite 3.53.
RUN mamba create -y -n wn -c conda-forge \
        windninja \
        fastapi \
        uvicorn-standard \
        rasterio \
        numpy \
    && mamba clean -afy

# Pôr o ambiente `wn` à frente no PATH dispensa `conda activate`, que não
# funciona em CMD/ENTRYPOINT sem shell de login.
ENV PATH=/opt/conda/envs/wn/bin:$PATH \
    WINDNINJA_DATA=/opt/conda/envs/wn/share/windninja \
    PYTHONUNBUFFERED=1

COPY services/windninja/main.py ./main.py

# Verificação do plano nº1: confirmar que o WindNinja_cli corre dentro
# do container. Falha o build se o binário não existir, em vez de deixar
# a avaria aparecer só no primeiro pedido.
RUN WindNinja_cli --help > /dev/null 2>&1 || \
    (echo "WindNinja_cli não responde" && exit 1)

EXPOSE 8080

# Um worker só: cada corrida do WindNinja é CPU-bound e usa até 255 MB;
# vários workers em paralelo multiplicariam o pico de memória sem ganho,
# porque o chamador já serializa as corridas (ver fetch_wind_fields).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
