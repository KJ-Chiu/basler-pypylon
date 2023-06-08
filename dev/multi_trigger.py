import math
from time import perf_counter_ns, sleep
from pypylon import pylon

from collections import deque
from datetime import datetime, timedelta

from typing import Deque

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
FRAME_RATE = 160
FRAME_GAP_NANO = int(1000000000 / FRAME_RATE)


class Camera(pylon.ImageEventHandler):
    def __init__(self, gotFrame):
        super().__init__()
        self.gotFrame = gotFrame

        self.benchmark = 0
        self.pause = False

        converter = pylon.ImageFormatConverter()
        converter.OutputPixelFormat = pylon.PixelType_BGR8packed
        converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned
        self.converter = converter

    def OnImagesSkipped(self, camera, countOfSkippedImages):
        # [Debug]
        # print(
        #     "OnImagesSkipped event for device ", camera.GetDeviceInfo().GetModelName()
        # )
        # print(countOfSkippedImages, " images have been skipped.")
        # print()
        pass

    def OnImageGrabbed(self, camera, grabResult):
        # print("OnImageGrabbed event for device ", camera.GetDeviceInfo().GetModelName())

        if self.pause is True or grabResult.GrabSucceeded() is False:
            # [Debug]
            print(
                "[Failed] OnImageGrabbed event for device ",
                camera.GetDeviceInfo().GetModelName(),
                "Error: ",
                grabResult.ErrorCode,
                grabResult.ErrorDescription,
            )
            grabResult.Release()
            return

        try:
            deviceTimestamp = grabResult.ChunkTimestamp.Value
            if self.benchmark == 0:
                self.benchmark = deviceTimestamp

            image = self.converter.Convert(grabResult)

            afterBenchmark = deviceTimestamp - self.benchmark
            self.gotFrame(
                image.GetArray(),
                afterBenchmark,
                deviceTimestamp,
                grabResult.ChunkCounterValue.Value,
            )
        except Exception as e:
            print(e)
            raise e

        grabResult.Release()


class CameraController:
    def __init__(
        self,
        deviceName,
        ic,
        frameQueue: Deque,
    ):
        self.deviceName = deviceName

        camera = Camera(self.gotFrame)
        ic.RegisterImageEventHandler(
            camera, pylon.RegistrationMode_Append, pylon.Cleanup_Delete
        )
        ic.Open()

        # Print the model name of the camera.
        print("Using device ", ic.GetDeviceInfo().GetModelName())

        ic.Width.SetValue(FRAME_WIDTH)
        ic.Height.SetValue(FRAME_HEIGHT)

        ic.Gamma.SetValue(1.5)
        ic.ExposureAuto.SetValue("Continuous")
        ic.AutoExposureTimeUpperLimit.SetValue(1000000 / FRAME_RATE)
        ic.AutoTargetBrightness.SetValue(0.2)
        ic.AutoFunctionROISelector.SetValue("ROI1")
        ic.AutoFunctionROIUseBrightness.SetValue(True)

        ic.DeviceLinkSelector.SetValue(0)
        ic.DeviceLinkThroughputLimitMode.SetValue("Off")

        # Make sure the frame trigger is set to Off to enable free run
        ic.TriggerSelector.SetValue("FrameStart")
        ic.TriggerMode.SetValue("Off")
        ic.TriggerSource.SetValue("Software")
        ic.AcquisitionFrameRateEnable.SetValue(True)
        ic.AcquisitionFrameRate.SetValue(float(FRAME_RATE))

        ic.AcquisitionMode.SetValue("Continuous")

        ic.ChunkModeActive.SetValue(True)
        ic.ChunkSelector.SetValue("ExposureTime")
        ic.ChunkEnable.SetValue(True)
        ic.ChunkSelector.SetValue("Timestamp")
        ic.ChunkEnable.SetValue(True)
        ic.ChunkSelector.SetValue("CounterValue")
        ic.ChunkEnable.SetValue(True)

        ic.OutputQueueSize = 30
        ic.MaxNumBuffer = 30

        self.ic = ic
        self.camera = camera

        self.counter = 0

        self.benchmarkTime = None

        self.frameQueue = frameQueue

        # [Debug]
        self.recents: deque[datetime] = deque(maxlen=FRAME_RATE * 2)
        self.lastTrackingAt: datetime = datetime.now()

    def gotFrame(self, image, afterBenchmark, deviceTimestamp, deviceFrameNumber):
        if self.benchmarkTime is None:
            self.benchmarkTime = datetime.now()

        timeEpoch: datetime = self.benchmarkTime + timedelta(
            microseconds=afterBenchmark / 1000
        )

        # [Debug]
        self.recents.append(timeEpoch)
        if (datetime.now() - self.lastTrackingAt).total_seconds() > 1 and len(
            self.recents
        ) > 1:
            print(
                "{} Frame AVG: {}/s".format(
                    self.deviceName,
                    int(
                        len(self.recents)
                        / (self.recents[-1] - self.recents[0]).total_seconds()
                    ),
                )
            )

        self.frameQueue.append(
            (timeEpoch, image.copy(), deviceTimestamp, deviceFrameNumber)
        )

    def start(self):
        print(
            "Starting {} at {}".format(
                self.deviceName, datetime.now().strftime("%H:%M:%S:%f")
            )
        )
        self.ic.TriggerMode.SetValue("On")
        self.ic.StartGrabbing(
            pylon.GrabStrategy_OneByOne, pylon.GrabLoop_ProvidedByInstantCamera
        )

    def freeRun(self):
        if self.benchmarkTime is None:
            self.benchmarkTime = datetime.now()
        try:
            self.ic.StopGrabbing()
        except:
            pass
        self.ic.TriggerMode.SetValue("Off")
        self.ic.StartGrabbing(
            pylon.GrabStrategy_LatestImages, pylon.GrabLoop_ProvidedByInstantCamera
        )

    def trigger(self):
        self.ic.TriggerSoftware.Execute()

    def benchmarkReset(self, benchmarkTime: datetime):
        self.benchmarkTime = benchmarkTime
        self.camera.benchmark = 0

    def pause(self):
        self.camera.pause = True

    def resume(self):
        self.camera.pause = False

    def stop(self):
        self.ic.AcquisitionStop.Execute()
        self.ic.Close()
        print("Camera Stop {}".format(self.deviceName))


def getCamera(
    deviceName: str,
    frameQueue: Deque,
) -> tuple[bool, CameraController]:
    print("Basler Get Camera: {}".format(deviceName))
    tlFactory = pylon.TlFactory.GetInstance()
    devices = tlFactory.EnumerateDevices()

    ic = None
    for device in devices:
        if deviceName != device.GetUserDefinedName():
            continue
        ic = pylon.InstantCamera(tlFactory.CreateDevice(device))
        break

    cameraController = CameraController(
        deviceName=deviceName,
        ic=ic,
        frameQueue=frameQueue,
    )

    return True, cameraController


CAMS = ["3rd-left", "3rd-right"]


def main():
    controllers = []
    for CAM in CAMS:
        camQueue = deque(maxlen=FRAME_RATE * 3)
        _, controller = getCamera(deviceName=CAM, frameQueue=camQueue)
        controllers.append((controller, camQueue))

    # [MODE] free run mode
    # for controller in controllers:
    #     controller[0].freeRun()

    # [MODE] trigger mode
    for controller in controllers:
        controller[0].start()

    startAt = perf_counter_ns()
    counter = 0
    scheduleAt = perf_counter_ns()
    while counter < FRAME_RATE * 5:
        while scheduleAt > perf_counter_ns():
            sleep(0)
        # [MODE] trigger mode
        for controller in controllers:
            controller[0].trigger()
        scheduleAt += FRAME_GAP_NANO
        scheduleDelta = perf_counter_ns() - scheduleAt
        # Skip if is already overtime
        if scheduleDelta > 0:
            scheduleAt += math.ceil(scheduleDelta / FRAME_GAP_NANO) * FRAME_GAP_NANO
        counter += 1

    print(
        "Counter: {}, Time Cost: {}".format(
            counter, ((perf_counter_ns() - startAt) // 1000000) / 1000
        )
    )

    for controller in controllers:
        controller[0].stop()


main()
