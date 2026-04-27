# Install script for directory: /home/lyu/BuildAC/Ninja_optimized/project/Catch2

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "/usr/local")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Install shared libraries without execute permission?
if(NOT DEFINED CMAKE_INSTALL_SO_NO_EXE)
  set(CMAKE_INSTALL_SO_NO_EXE "1")
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

# Set default install directory permissions.
if(NOT DEFINED CMAKE_OBJDUMP)
  set(CMAKE_OBJDUMP "/usr/bin/objdump")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("/home/lyu/BuildAC/Ninja_optimized/project/catch_build/src/cmake_install.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/Catch2" TYPE FILE FILES
    "/home/lyu/BuildAC/Ninja_optimized/project/catch_build/Catch2Config.cmake"
    "/home/lyu/BuildAC/Ninja_optimized/project/catch_build/Catch2ConfigVersion.cmake"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/doc/Catch2" TYPE DIRECTORY FILES "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/docs/" REGEX "/doxygen$" EXCLUDE)
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/Catch2" TYPE FILE FILES
    "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/extras/ParseAndAddCatchTests.cmake"
    "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/extras/Catch.cmake"
    "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/extras/CatchAddTests.cmake"
    "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/extras/CatchShardTests.cmake"
    "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/extras/CatchShardTestsImpl.cmake"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/Catch2" TYPE FILE FILES
    "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/extras/gdbinit"
    "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/extras/lldbinit"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  set(install_pkgconfdir "share/pkgconfig")
set(impl_pc_file "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/CMake/catch2.pc.in")
set(main_pc_file "/home/lyu/BuildAC/Ninja_optimized/project/Catch2/CMake/catch2-with-main.pc.in")
set(Catch2_VERSION 3.14.0)
set(include_dir "include")
set(lib_dir "lib")
         message(STATUS "DESTDIR: $ENV{DESTDIR}")
         set(DESTDIR_PREFIX "")
         if (DEFINED ENV{DESTDIR})
           set(DESTDIR_PREFIX "$ENV{DESTDIR}")
         endif ()
         message(STATUS "PREFIX: ${DESTDIR_PREFIX}")
         set(lib_name "Catch2")
         configure_file(
           "${impl_pc_file}"
           "${DESTDIR_PREFIX}${CMAKE_INSTALL_PREFIX}/${install_pkgconfdir}/catch2.pc"
           @ONLY
         )

         set(lib_name "Catch2Main")
         configure_file(
           "${main_pc_file}"
           "${DESTDIR_PREFIX}${CMAKE_INSTALL_PREFIX}/${install_pkgconfdir}/catch2-with-main.pc"
           @ONLY
         )
       
endif()

if(CMAKE_INSTALL_COMPONENT)
  set(CMAKE_INSTALL_MANIFEST "install_manifest_${CMAKE_INSTALL_COMPONENT}.txt")
else()
  set(CMAKE_INSTALL_MANIFEST "install_manifest.txt")
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
file(WRITE "/home/lyu/BuildAC/Ninja_optimized/project/catch_build/${CMAKE_INSTALL_MANIFEST}"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
