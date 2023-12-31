import sys
from multiprocessing import Process, Queue
from time import sleep

sys.path.insert(0, './yolov5')
from real_track import real_track
from yolov5.utils.google_utils import attempt_download
from yolov5.models.experimental import attempt_load
from yolov5.utils.datasets import LoadImages, LoadStreams
from yolov5.utils.general import check_img_size, non_max_suppression, scale_coords, \
    check_imshow
from yolov5.utils.torch_utils import select_device, time_synchronized
from deep_sort_pytorch.utils.parser import get_config
from deep_sort_pytorch.deep_sort import DeepSort
import argparse
import os
import platform
import shutil
import time
from pathlib import Path
import cv2
import torch
import torch.backends.cudnn as cudnn
from onvif import ONVIFCamera
from threading import Thread
import zeep

# import cruise_track

palette = (2 ** 11 - 1, 2 ** 15 - 1, 2 ** 20 - 1)
mycam = ONVIFCamera('192.168.1.125', 80, 'admin', 'a12345678')
media = mycam.create_media_service()
ptz = mycam.create_ptz_service()
media_profile = media.GetProfiles()[0]
_AbsoluteMove = ptz.create_type('AbsoluteMove')
_AbsoluteMove.ProfileToken = media_profile.token
# 定义为是否有检测到
xxxx = 0
# 判断是否已开启自动巡航
cruise = 0
# 判断是否处于巡航中
re_cruise = 0
# 判断是否处于jjj函数中
is_jjj = 0
# 判断是否处于hhh函数中
is_hhh = 1
# 判断是否退出自动巡航线程
_th1 = 0
# 自动巡航的线程名
# th1 = None
# 是否1秒后仍未检测到物体
is_not_hhh = 0


# 自动巡航进程函数
def real_move():
    global _th1
    global re_cruise
    request = ptz.create_type('GetConfigurationOptions')
    request.ConfigurationToken = media_profile.PTZConfiguration.token
    ptz_configuration_options = ptz.GetConfigurationOptions(request)
    request = ptz.create_type('ContinuousMove')
    request.ProfileToken = media_profile.token
    ptz.Stop({'ProfileToken': media_profile.token})

    if request.Velocity is None:
        request.Velocity = ptz.GetStatus({'ProfileToken': media_profile.token}).Position
        request.Velocity.PanTilt.space = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].URI
        request.Velocity.Zoom.space = ptz_configuration_options.Spaces.ContinuousZoomVelocitySpace[0].URI

    _AbsoluteMove = ptz.create_type('AbsoluteMove')
    _AbsoluteMove.ProfileToken = media_profile.token
    ptz.Stop({'ProfileToken': media_profile.token})
    _AbsoluteMove.Position = ptz.GetStatus({'ProfileToken': media_profile.token}).Position
    _AbsoluteMove.Speed = ptz.GetStatus({'ProfileToken': media_profile.token}).Position

    _AbsoluteMove.Position.PanTilt.x = 0
    _AbsoluteMove.Speed.PanTilt.x = 6
    _AbsoluteMove.Position.PanTilt.y = 1
    _AbsoluteMove.Speed.PanTilt.y = 6

    _AbsoluteMove.Position.Zoom = 0
    _AbsoluteMove.Speed.Zoom = 6
    request.Velocity.PanTilt.x = 0.3
    request.Velocity.PanTilt.y = 0.3

    ptz.AbsoluteMove(_AbsoluteMove)
    print('init...')
    while 1:
        if ptz.GetStatus({'ProfileToken': media_profile.token}).Position.PanTilt.y == 1:
            break
    print('move...')
    while 1:
        print('zai')
        if _th1:
            _th1 = 0
            re_cruise = 0
            break
        request.Velocity.PanTilt.y = -0.3
        ptz.ContinuousMove(request)
        while 1:
            if _th1:
                break
            if ptz.GetStatus({'ProfileToken': media_profile.token}).Position.PanTilt.y <= 0.4:
                break
        request.Velocity.PanTilt.y = 0.3
        ptz.ContinuousMove(request)
        while 1:
            if _th1:
                break
            if ptz.GetStatus({'ProfileToken': media_profile.token}).Position.PanTilt.y == 1:
                break


def xyxy_to_xywh(*xyxy):
    """" Calculates the relative bounding box from absolute pixel values. """
    bbox_left = min([xyxy[0].item(), xyxy[2].item()])
    bbox_top = min([xyxy[1].item(), xyxy[3].item()])
    bbox_w = abs(xyxy[0].item() - xyxy[2].item())
    bbox_h = abs(xyxy[1].item() - xyxy[3].item())
    x_c = (bbox_left + bbox_w / 2)
    y_c = (bbox_top + bbox_h / 2)
    w = bbox_w
    h = bbox_h
    return x_c, y_c, w, h


def compute_color_for_labels(label):
    """
    Simple function that adds fixed color depending on the class
    """
    color = [int((p * (label ** 2 - label + 1)) % 255) for p in palette]
    return tuple(color)


# 画图
def draw_boxes(img, bbox, identities=None, offset=(0, 0)):
    for i, box in enumerate(bbox):
        # 只取一直跟踪的那个
        if box[-1] == identities:
            x1, y1, x2, y2 = [int(i) for i in box]
            # print(x1, y1, x2, y2)
            x1 += offset[0]
            x2 += offset[0]
            y1 += offset[1]
            y2 += offset[1]
            # print(img.shape)
            # box text and bar
            # id = int(identities[i]) if identities is not None else 0
            # color = compute_color_for_labels(id)
            # label = '{}{:d}'.format("", id)
            # t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_PLAIN, 2, 2)[0]
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
            break
            # cv2.rectangle(
        #     img, (x1, y1), (x1 + t_size[0] + 3, y1 + t_size[1] + 4), color, -1)
        # cv2.putText(img, label, (x1, y1 +
        #                        t_size[1] + 4), cv2.FONT_HERSHEY_PLAIN, 2, [255, 255, 255], 2)
    return img


# 未检测1秒后才停止
def hhh(_time):
    global xxxx
    global is_hhh
    global is_not_hhh
    while 1:
        if time.time() - _time >= 1:
            is_not_hhh = 1
            break
        if xxxx:
            break
    ptz.Stop({'ProfileToken': media_profile.token})


# 5秒后未检测则巡航
def jjj(_time):
    global is_jjj
    global re_cruise
    while 1:
        print('正在jjj中')
        print(f'xxxx={xxxx}')
        if xxxx:
            is_jjj = 0
            break
        sleep(1)
        if time.time() - _time > 5 and (not re_cruise):
            th1 = Thread(target=real_move())
            th1.start()
            re_cruise = 1
            is_jjj = 0
            break


def detect(opt):
    global re_cruise
    global xxxx
    global cruise
    global is_jjj
    global is_hhh
    global _th1
    # global th1
    global is_not_hhh
    out, source, yolo_weights, deep_sort_weights, show_vid, save_vid, save_txt, imgsz, cruise = \
        opt.output, opt.source, opt.yolo_weights, opt.deep_sort_weights, opt.show_vid, opt.save_vid, opt.save_txt, opt.img_size, opt.cruise
    webcam = source == '0' or source.startswith(
        'rtsp') or source.startswith('http') or source.endswith('.txt')
    if cruise:
        th1 = Thread(target=real_move)
        th1.start()
        re_cruise = 1
    # initialize deepsort
    cfg = get_config()
    cfg.merge_from_file(opt.config_deepsort)
    attempt_download(deep_sort_weights, repo='mikel-brostrom/Yolov5_DeepSort_Pytorch')
    deepsort = DeepSort(cfg.DEEPSORT.REID_CKPT,
                        max_dist=cfg.DEEPSORT.MAX_DIST, min_confidence=cfg.DEEPSORT.MIN_CONFIDENCE,
                        nms_max_overlap=cfg.DEEPSORT.NMS_MAX_OVERLAP, max_iou_distance=cfg.DEEPSORT.MAX_IOU_DISTANCE,
                        max_age=cfg.DEEPSORT.MAX_AGE, n_init=cfg.DEEPSORT.N_INIT, nn_budget=cfg.DEEPSORT.NN_BUDGET,
                        use_cuda=True)

    # Initialize
    device = select_device(opt.device)
    if os.path.exists(out):
        shutil.rmtree(out)  # delete output folder
    os.makedirs(out)  # make new output folder
    half = device.type != 'cpu'  # half precision only supported on CUDA

    # Load model
    model = attempt_load(yolo_weights, map_location=device)  # load FP32 model
    stride = int(model.stride.max())  # model stride
    imgsz = check_img_size(imgsz, s=stride)  # check img_size
    names = model.module.names if hasattr(model, 'module') else model.names  # get class names
    if half:
        model.half()  # to FP16

    # Set Dataloader
    vid_path, vid_writer = None, None
    # Check if environment supports image displays
    if show_vid:
        show_vid = check_imshow()

    if webcam:
        cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz, stride=stride)
    else:
        dataset = LoadImages(source, img_size=imgsz)

    # Get names and colors
    names = model.module.names if hasattr(model, 'module') else model.names

    # Run inference
    if device.type != 'cpu':
        model(torch.zeros(1, 3, imgsz, imgsz).to(device).type_as(next(model.parameters())))  # run once
    t0 = time.time()

    save_path = str(Path(out))
    txt_path = str(Path(out)) + '/results.txt'
    #
    id = -1
    for frame_idx, (path, img, im0s, vid_cap) in enumerate(dataset):
        img = torch.from_numpy(img).to(device)
        img = img.half() if half else img.float()  # uint8 to fp16/32
        img /= 255.0  # 0 - 255 to 0.0 - 1.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)

        # Inference
        # 计算时间
        # t1 = time_synchronized()
        pred = model(img, augment=opt.augment)[0]

        # Apply NMS
        pred = non_max_suppression(
            pred, opt.conf_thres, opt.iou_thres, classes=opt.classes, agnostic=opt.agnostic_nms)
        # t2 = time_synchronized()

        # Process detections
        for i, det in enumerate(pred):  # detections per image
            if webcam:  # batch_size >= 1
                p, s, im0 = path[i], '%g: ' % i, im0s[i].copy()
            else:
                p, s, im0 = path, '', im0s

            s += '%gx%g ' % img.shape[2:]  # print string
            save_path = str(Path(out) / Path(p).name)

            if det is not None and len(det):
                if cruise and re_cruise:
                    _th1 = 1
                    ptz.Stop({'ProfileToken': media_profile.token})
                    re_cruise = 0
                    is_jjj=0
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(
                    img.shape[2:], det[:, :4], im0.shape).round()

                # Print results
                for c in det[:, -1].unique():
                    n = (det[:, -1] == c).sum()  # detections per class
                    s += '%g %ss, ' % (n, names[int(c)])  # add to string

                xywh_bboxs = []
                confs = []

                # Adapt detections to deep sort input format
                for *xyxy, conf, cls in det:
                    # to deep sort format
                    x_c, y_c, bbox_w, bbox_h = xyxy_to_xywh(*xyxy)
                    xywh_obj = [x_c, y_c, bbox_w, bbox_h]
                    xywh_bboxs.append(xywh_obj)
                    confs.append([conf.item()])

                xywhs = torch.Tensor(xywh_bboxs)
                confss = torch.Tensor(confs)

                # pass detections to deepsort
                outputs = deepsort.update(xywhs, confss, im0)
                # draw boxes for visualization
                if len(outputs) > 0:
                    xxxx = 1
                    bbox_xyxys = outputs[:, :4]
                    # 追踪
                    if id in bbox_xyxys[:, -1]:
                        for _bbox in bbox_xyxys:
                            if _bbox[-1] == id:
                                real_track(_bbox)
                                # box_height = _bbox[3] - _bbox[1]
                                break
                    else:
                        id = bbox_xyxys[0][-1]
                        # box_height = bbox_xyxys[0][3] - bbox_xyxys[0][1]
                        real_track(bbox_xyxys[0])
                    # 计算框高
                    # _AbsoluteMove.Position = ptz.GetStatus({'ProfileToken': media_profile.token}).Position
                    # if (box_height > 130 and _AbsoluteMove.Position.Zoom.x != 0) or box_height < 100:
                    #     _AbsoluteMove.Speed = ptz.GetStatus({'ProfileToken': media_profile.token}).Position
                    #     if box_height > 130 and _AbsoluteMove.Position.Zoom.x != 0:
                    #         # print(_AbsoluteMove.Position.Zoom)
                    #         if _AbsoluteMove.Position.Zoom.x - 0.05 >= 0:
                    #             _AbsoluteMove.Position.Zoom.x -= 0.05
                    #         else:
                    #             _AbsoluteMove.Position.Zoom.x = 0
                    #         _AbsoluteMove.Speed.Zoom.x = 10
                    #         _AbsoluteMove.Speed.PanTilt.x = 0
                    #         _AbsoluteMove.Speed.PanTilt.y = 0
                    #         ptz.AbsoluteMove(_AbsoluteMove)
                    #     elif box_height < 100:
                    #         print(666)
                    #         if _AbsoluteMove.Position.Zoom.x + 0.05 <= 1:
                    #             _AbsoluteMove.Position.Zoom.x += 0.05
                    #         else:
                    #             _AbsoluteMove.Position.Zoom.x = 1
                    #         _AbsoluteMove.Speed.Zoom.x = 10
                    #         _AbsoluteMove.Speed.PanTilt.x = 0
                    #         _AbsoluteMove.Speed.PanTilt.y = 0
                    #         ptz.AbsoluteMove(_AbsoluteMove)
                    identities = outputs[:, -1]
                    draw_boxes(im0, bbox_xyxys, id)
                    xxxx = 0
                    is_hhh = 0
            else:
                print(cruise, re_cruise, is_jjj)
                print(cruise and not re_cruise and not is_jjj)
                if not is_hhh:
                    th2 = Thread(target=hhh, args=(time.time(),))
                    th2.start()
                    is_hhh = 1
                if cruise and not re_cruise and not is_jjj:
                    is_jjj = 1
                    th3 = Thread(target=jjj, args=(time.time(),))
                    th3.start()
                # 失去目标后，1秒后恢复

                # if not cruise:
                #     ptz.Stop({'ProfileToken': media_profile.token})
                if is_not_hhh:
                    is_not_hhh = 0
                    _AbsoluteMove.Position = ptz.GetStatus({'ProfileToken': media_profile.token}).Position
                    if _AbsoluteMove.Position.Zoom.x != 0:
                        _AbsoluteMove.Speed = ptz.GetStatus({'ProfileToken': media_profile.token}).Position
                        _AbsoluteMove.Position.Zoom.x = 0
                        _AbsoluteMove.Speed.Zoom.x = 1
                        _AbsoluteMove.Speed.PanTilt.x = 0
                        _AbsoluteMove.Speed.PanTilt.y = 0
                        ptz.AbsoluteMove(_AbsoluteMove)
                deepsort.increment_ages()
            # Print time (inference + NMS)
            # print('%sDone. (%.3fs)' % (s, t2 - t1))
            # 展示视频流
            if show_vid:
                # cv2.putText(img, text, (5, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255 ), 2)
                cv2.imshow(p, im0)
    # if save_txt or save_vid:
    #     print('Results saved to %s' % os.getcwd() + os.sep + out)
    #     if platform == 'darwin':  # MacOS
    #         os.system('open ' + save_path)
    # print('Done. (%.3fs)' % (time.time() - t0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--yolo_weights', type=str, default=r"G:\yolo_tracking-v.2.0\yolov5\runs\train\exp12\weights"
                                                            r"\best.pt", help='model.pt path')
    parser.add_argument('--deep_sort_weights', type=str, default='deep_sort_pytorch/deep_sort/deep/checkpoint/ckpt.t7',
                        help='ckpt.t7 path')
    # file/folder, 0 for webcam
    parser.add_argument('--source', type=str, default=r'rtsp://admin:a12345678@192.168.1.125:554/Streaming/Channels'
                                                      r'/101?transportmode=unicast&profile=Profile_1', help='source')
    parser.add_argument('--output', type=str, default='inference/output', help='output folder')  # output folder
    # 无效
    parser.add_argument('--img-size', type=int, default=640, help='inference size (pixels)')
    parser.add_argument('--conf-thres', type=float, default=0.6, help='object confidence threshold')
    parser.add_argument('--iou-thres', type=float, default=0.6, help='IOU threshold for NMS')
    parser.add_argument('--fourcc', type=str, default='mp4v', help='output video codec (verify ffmpeg support)')
    parser.add_argument('--device', default='', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
    parser.add_argument('--show-vid', default=True, action='store_true', help='display tracking video results')
    parser.add_argument('--save-vid', action='store_true', help='save video tracking results')
    parser.add_argument('--save-txt', default=False, action='store_true', help='save MOT compliant results to *.txt')
    # class 0 is person, 1 is bycicle, 2 is car... 79 is oven
    # 人
    parser.add_argument('--classes', nargs='+', default=None, type=int, help='filter by class')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    parser.add_argument("--config_deepsort", type=str, default="deep_sort_pytorch/configs/deep_sort.yaml")
    parser.add_argument("--cruise", default=True, help='是否开启巡航')
    args = parser.parse_args()
    args.img_size = check_img_size(args.img_size)

    with torch.no_grad():
        detect(args)
