@rem Builds lib/acl_sample.dll. Needs MSVC and ACL 2.1.0 (git clone --branch v2.1.0 --recurse-submodules https://github.com/nfrechette/acl.git)
@rem usage: build.bat <path to acl checkout>
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cl /nologo /O2 /EHsc /std:c++17 /LD /MT /I%1\includes /I%1\external\rtm\includes "%~dp0acl_sample.cpp" /Fe:"%~dp0..\..\lib\acl_sample.dll" /Fo:"%TEMP%\\"
