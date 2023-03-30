# ===============================================================================
#    This sample illustrates how to grab and process images using the CInstantCamera class.
#    The images are grabbed and processed asynchronously, i.e.,
#    while the application is processing a buffer, the acquisition of the next buffer is done
#    in parallel.
#
#    The CInstantCamera class uses a pool of buffers to retrieve image data
#    from the camera device. Once a buffer is filled and ready,
#    the buffer can be retrieved from the camera object for processing. The buffer
#    and additional image data are collected in a grab result. The grab result is
#    held by a smart pointer after retrieval. The buffer is automatically reused
#    when explicitly released or when the smart pointer object is destroyed.
# ===============================================================================
from collections import deque
from datetime import datetime
import threading
import cv2
import numpy as np
from pypylon import pylon
from pypylon import genicam

import sys

FRAME_WIDTH = 720
FRAME_HEIGHT = 540

FRAME_RATE = 450

DURATION = 3

# The exit code of the sample application.
exitCode = 0

# Create an instant camera object with the camera device found first.
camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
camera.Open()

# Print the model name of the camera.
print("Using device ", camera.GetDeviceInfo().GetModelName())

camera.Width.SetValue(FRAME_WIDTH)
camera.Height.SetValue(FRAME_HEIGHT)
camera.CenterX.SetValue(True)
camera.CenterY.SetValue(True)

camera.PixelFormat.SetValue("BGR8")
camera.Gamma.SetValue(1)
camera.ExposureTime = int(1000000 / FRAME_RATE)

camera.AcquisitionFrameRateEnable.SetValue(True)
camera.AcquisitionFrameRate.SetValue(FRAME_RATE)

# The parameter MaxNumBuffer can be used to control the count of buffers
# allocated for grabbing. The default value of this parameter is 10.
camera.MaxNumBuffer = 10

# Start the grabbing of c_countOfImagesToGrab images.
# The camera device is parameterized with a default configuration which
# sets up free-running continuous acquisition.
# camera.StartGrabbingMax(FRAME_RATE * 6)
camera.StartGrabbing()

images: deque[np.ndarray] = deque(maxlen=FRAME_RATE * DURATION)
timestamps: deque[datetime] = deque(maxlen=FRAME_RATE * DURATION)

converter = pylon.ImageFormatConverter()
converter.OutputPixelFormat = pylon.PixelType_BGR8packed
# converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

stopEvent = threading.Event()


def grab():
    grabResult = camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)

    # Image grabbed successfully?
    if grabResult.GrabSucceeded():
        img = converter.Convert(grabResult)
        images.append(img.GetArray())
        timestamps.append(datetime.now())
    else:
        print("Error: ", grabResult.ErrorCode, grabResult.ErrorDescription)
    grabResult.Release()


seq = 0
while True:
    grab()
    if seq % 6 == 0:
        cv2.imshow("Cur", cv2.rotate(images[-1], cv2.ROTATE_90_CLOCKWISE))
    seq += 1

    k = cv2.waitKey(1) & 0xFF
    if k == 13:
        print("start record")
        images.clear()
        timestamps.clear()
        while len(images) < FRAME_RATE * DURATION:
            grab()

        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        out = cv2.VideoWriter(
            "slomo_{}-{}.avi".format(
                timestamps[0].strftime("%H%M%S"), timestamps[-1].strftime("%H%M%S")
            ),
            fourcc,
            60,
            (FRAME_WIDTH, FRAME_HEIGHT),
        )
        for image in list(images):
            out.write(image)
        out.release()
        continue

    if k == 27:
        break

camera.StopGrabbing()
camera.Close()
