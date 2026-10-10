@echo off

rem Thonny AIA: build and output folders, the Python to bundle and Inno Setup can be
rem given from outside (keep the build tree out of a synced folder such as OneDrive)
if not defined BUILDDIR set BUILDDIR=build
if not defined DISTDIR set DISTDIR=dist
if not defined PYTHONDIR set PYTHONDIR=C:\Program Files\Python314
if not defined ISCC set ISCC=C:\Program Files (x86)\Inno Setup 6\iscc
del %BUILDDIR% /Q
rmdir %BUILDDIR% /S /Q
mkdir %BUILDDIR%

@echo ............... COPYING PYTHON ...................................
xcopy "%PYTHONDIR%\*" %BUILDDIR% /S /E /K>NUL
del %BUILDDIR%\__install__.json /Q>NUL 2>NUL
@echo ............... COPYING OTHER STUFF ...................................
copy ThonnyRunner314\x64\Release\thonny.exe %BUILDDIR%\thonny-aia.exe /Y
copy thonny_python.ini %BUILDDIR%

@echo ............... INSTALLING DEPS ...................................

%BUILDDIR%\python -s -m pip install --no-warn-script-location --no-cache-dir wheel

%BUILDDIR%\python -s -m pip install --no-warn-script-location --no-cache-dir --no-binary mypy -r ..\requirements-regular-bundle.txt

@echo ............... INSTALLING THONNY ...................................
rem Thonny AIA: this fork from the source tree (pulls the AI SDKs as its dependencies)
%BUILDDIR%\python -s -m pip install --no-warn-script-location --no-cache-dir ..\..
@rem %BUILDDIR%\python -s -m pip install --no-warn-script-location ..\..\dist\thonny-4.2.0.dev1-py3-none-any.whl

@echo ............... CLEANING PYTHON ............................
@rem move following 3 files to avoid confusion (user may think they're Thonny license etc.)
move %BUILDDIR%\LICENSE.txt %BUILDDIR%\PYTHON_LICENSE.txt
move %BUILDDIR%\README.txt %BUILDDIR%\PYTHON_README.txt
move %BUILDDIR%\NEWS.txt %BUILDDIR%\PYTHON_NEWS.txt

del /S "%BUILDDIR%\*.pyc">NUL
@rem del /S "%BUILDDIR%\*.lib">NUL
del /S "%BUILDDIR%\tcl\*.lib">NUL
del /S "%BUILDDIR%\*.a">NUL
del /S "%BUILDDIR%\*.chm">NUL

rmdir %BUILDDIR%\Doc /S /Q>NUL
@rem rmdir %BUILDDIR%\include /S /Q>NUL
@rem rmdir %BUILDDIR%\libs /S /Q>NUL
rmdir %BUILDDIR%\Tools /S /Q>NUL
del "%BUILDDIR%\Scripts\*" /Q>NUL

copy .\pip.bat "%BUILDDIR%\Scripts\pip.bat"
copy .\pip.bat "%BUILDDIR%\Scripts\pip3.bat"
copy .\pip.bat "%BUILDDIR%\Scripts\pip3.14.bat"

rmdir %BUILDDIR%\lib\test /S /Q>NUL

del %BUILDDIR%\tcl\*.sh /Q>NUL
del %BUILDDIR%\tcl\tcl8.6\clock.tcl>NUL
del %BUILDDIR%\tcl\tcl8.6\safe.tcl>NUL
rmdir %BUILDDIR%\tcl\tix8.4.3\demos /S /Q>NUL

rmdir %BUILDDIR%\tcl\tk8.6\demos /S /Q>NUL
rmdir %BUILDDIR%\tcl\tk8.6\msgs /S /Q>NUL

rmdir %BUILDDIR%\tcl\tcl8.6\opt0.4 /S /Q>NUL
rmdir %BUILDDIR%\tcl\tcl8.6\msgs /S /Q>NUL
rmdir %BUILDDIR%\tcl\tcl8.6\tzdata /S /Q>NUL

rmdir %BUILDDIR%\lib\site-packages\pylint\test /S /Q>NUL
rmdir %BUILDDIR%\lib\site-packages\mypy\test /S /Q>NUL


@echo ............... ADDING LICENSES ...................................
copy ..\..\LICENSE.txt %BUILDDIR% /Y>NUL
mkdir %BUILDDIR%\licenses
xcopy ..\..\licenses\* %BUILDDIR%\licenses /S /E /K>NUL

@echo ............... ADDING OTHER STUFF ...................................
copy ..\..\CHANGELOG.rst %BUILDDIR% /Y>NUL
copy ..\..\CREDITS.rst %BUILDDIR% /Y>NUL
copy ..\..\README.rst %BUILDDIR% /Y>NUL


@echo ............... CREATING INSTALLER ..........................
set /p VERSION=<%BUILDDIR%\Lib\site-packages\thonny\VERSION
"%ISCC%" /dInstallerPrefix=thonny-aia /dAppVer=%VERSION% /dArch=x64 /dSupportedArchitectures="x64compatible arm64" /dSourceFolder=%BUILDDIR% /O%DISTDIR% inno_setup.iss > %DISTDIR%\installer_building.log

@echo ............... CREATING ZIP ..........................
SET PATH=%PATH%;C:\Program Files\7-Zip
where 7z >NUL 2>NUL || goto :eof
copy ..\portable_thonny.ini %BUILDDIR%
cd %BUILDDIR%
7z a -tzip %DISTDIR%\thonny-aia-%VERSION%-windows-portable-x64.zip *
del portable_thonny.ini
cd ..

