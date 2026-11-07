unset(OPENCV_FOUND)
unset(OPENCV_INCLUDE_DIRS)
unset(OPENCV_LIB)

# OpenCV install prefix: override with -DOPENCV_PREFIX=/path/to/opencv
set(OPENCV_PREFIX "/usr/local/opencv4" CACHE PATH "OpenCV installation prefix")

find_path(OPENCV_INCLUDE_DIRS NAMES
  opencv2/core.hpp
  HINTS
  ${OPENCV_PREFIX}/include/opencv4
  /usr/include/opencv4
  /usr/local/include/opencv4
  /opt/homebrew/include/opencv4)

# opencv_videoio is linked on purpose: video file/stream decoding (cv::VideoCapture)
# is a supported use case, and on macOS it is the module that carries the FFmpeg
# backend. It also drags in opencv_imgcodecs (already needed) and, transitively,
# the system FFmpeg/x264 stack -- see README-macos for the runtime fixup of that chain.
# opencv_highgui stays OUT: no source in this project opens a window (the only
# reference is an unused #include in ORBSLAM/src/ORBextractor.cc).
foreach(LIB opencv_core opencv_imgproc opencv_features2d opencv_calib3d opencv_flann opencv_imgcodecs opencv_videoio)
        set(FOUND_LIB "FOUND_LIB-NOTFOUND")
        find_library(FOUND_LIB NAMES
          ${LIB}
          HINTS
          ${OPENCV_PREFIX}/lib
          /usr/lib
          /usr/local/lib
          /opt/homebrew/lib)
        if(FOUND_LIB)
          list(APPEND OPENCV_LIB ${FOUND_LIB})
        else()
          message(WARNING "OpenCV library not found: ${LIB}")
        endif()
        message("Found Lib: ${FOUND_LIB}")
endforeach(LIB)

if(OPENCV_INCLUDE_DIRS AND OPENCV_LIB)
  set(OPENCV_FOUND 1)
endif()

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(OpenCV2
  REQUIRED_VARS OPENCV_INCLUDE_DIRS OPENCV_LIB)
