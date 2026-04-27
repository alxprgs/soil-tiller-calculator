# Chocolatey release checklist

## Что публикуется

Windows-релиз публикуется как `SoilTillerCalculator-windows.zip`. Архив содержит
`SoilTillerCalculator.exe` и папку `_internal`; Chocolatey-пакет скачивает этот
zip, распаковывает его в `tools\app` и создаёт команды:

- `soil-tiller-calculator`
- `stc`

## Локальная проверка перед релизом

```powershell
python -m pytest
python -m PyInstaller --clean --noconfirm --onedir --windowed --name SoilTillerCalculator --collect-data soil_tiller_calculator src/soil_tiller_calculator/__main__.py
Compress-Archive -Path .\dist\SoilTillerCalculator\* -DestinationPath .\dist\SoilTillerCalculator-windows.zip -Force
$checksum = (Get-FileHash -LiteralPath .\dist\SoilTillerCalculator-windows.zip -Algorithm SHA256).Hash.ToLowerInvariant()
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-chocolatey-package.ps1 -Version 1.1.0 -ReleaseTag v1.1.0 -Checksum64 $checksum -OutputDirectory .\dist\chocolatey-local-check
```

Ожидаемый локальный результат:

- `dist\SoilTillerCalculator-windows.zip`
- `dist\chocolatey-local-check\soil-tiller-calculator.1.1.0.nupkg`

## Публикация через GitHub release

1. Закоммитьте изменения версии и упаковки.
2. Запушьте ветку в GitHub.
3. Создайте GitHub release с тегом `v1.1.0`.
4. Workflow `Release packages` должен:
   - собрать Linux binary;
   - собрать Windows onedir;
   - прикрепить `SoilTillerCalculator-windows.zip` к release;
   - собрать Chocolatey package;
   - выполнить `choco push`.

Если `choco push` проходит успешно, версия попадает в Chocolatey Community
Repository на moderation review.

## Если Chocolatey возвращает 403 Forbidden

`403 Forbidden` на шаге `choco push` обычно означает, что API key не даёт права
публиковать этот package id. Проверьте в GitHub repository settings secret
`CHOCOLATEY_API_KEY`:

- ключ должен быть от аккаунта Chocolatey, который является владельцем или
  maintainer пакета `soil-tiller-calculator`;
- ключ должен быть взят с `https://community.chocolatey.org/account`;
- если package id уже находится на moderation review, проверьте страницу пакета
  и комментарии модератора перед повторной отправкой.

Если автоматический push снова падает, скачайте artifact
`soil-tiller-calculator-chocolatey` из GitHub Actions и выполните push вручную
под нужным Chocolatey API key:

```powershell
choco apikey --key <CHOCOLATEY_API_KEY> --source https://push.chocolatey.org/
choco push .\soil-tiller-calculator.1.1.0.nupkg --source https://push.chocolatey.org/
```

