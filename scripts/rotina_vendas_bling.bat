@echo off
rem Rotina diária de vendas do Bling -> Sales Navigator (agendador do Windows).
rem Roda na pasta do projeto, grava a saída em logs\rotina_vendas_bling.log e devolve o código de saída do Python
rem (diferente de 0 = falhou; o Agendador de Tarefas mostra isso em "Último resultado").
cd /d "%~dp0.."
if not exist logs mkdir logs
echo ===== %date% %time% ===== >> logs\rotina_vendas_bling.log
set PYTHONIOENCODING=utf-8
venv\Scripts\python.exe main.py rotina_vendas_bling >> logs\rotina_vendas_bling.log 2>&1
set CODIGO=%ERRORLEVEL%
echo codigo de saida: %CODIGO% >> logs\rotina_vendas_bling.log
exit /b %CODIGO%
