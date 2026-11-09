@echo off
chcp 65001 >nul
title Grand Mobile Support Copilot - Batch Predict
echo ======================================================================
echo  🚀 Grand Mobile Support Copilot - Пакетный инференс (make predict)
echo ======================================================================
echo.

set INPUT_FILE=tickets_valid.jsonl
set OUTPUT_FILE=pred.jsonl

if not "%~1"=="" (
    set INPUT_FILE=%~1
    echo [INFO] Использован переданный файл: %INPUT_FILE%
) else (
    echo [INFO] Входной файл по умолчанию: %INPUT_FILE%
)

echo [INFO] Выходной файл: %OUTPUT_FILE%
echo.

python predict.py --in "%INPUT_FILE%" --out "%OUTPUT_FILE%"

echo.
echo ======================================================================
echo  🔍 Запуск автоматической верификации контракта:
echo ======================================================================
python verify_strict_compliance.py "%OUTPUT_FILE%"

echo.
echo [DONE] Обработка завершена! Результат сохранен в %OUTPUT_FILE%
pause
