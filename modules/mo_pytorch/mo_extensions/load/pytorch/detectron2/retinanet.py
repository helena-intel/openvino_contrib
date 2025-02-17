import torch
from collections import namedtuple

from ..hooks import OpenVINOTensor, forward_hook

from openvino.tools.mo.utils.error import Error

def inference(model, func, anchors, pred_logits, pred_anchor_deltas, image_sizes):
    # Concatenate the inputs (should be tracked)
    logist = torch.cat(pred_logits, dim=1).view(1, -1).sigmoid()
    deltas = torch.cat(pred_anchor_deltas, dim=1).view(1, -1)
    if not isinstance(logist, OpenVINOTensor) or not isinstance(deltas, OpenVINOTensor):
        raise Error('OpenVINOTensor is expected')

    # Create an alias
    class DetectionOutput(torch.nn.Module):
        def __init__(self, anchors):
            super().__init__()
            self.anchors = anchors
            self.variance_encoded_in_target = True
            self.nms_threshold = model.nms_threshold if hasattr(model, 'nms_threshold') else model.test_nms_thresh
            self.confidence_threshold = model.score_threshold if hasattr(model, 'score_threshold') else model.test_score_thresh
            in_features = model.in_features if hasattr(model, 'in_features') else model.head_in_features
            top_k_candidates = model.topk_candidates if hasattr(model, 'topk_candidates') else model.test_topk_candidates
            self.top_k = top_k_candidates * len(in_features)
            self.keep_top_k = self.top_k
            self.code_type = 'caffe.PriorBoxParameter.CENTER_SIZE'

        def state_dict(self):
            return {'anchors': anchors}

    outputs = [OpenVINOTensor(), OpenVINOTensor(), OpenVINOTensor()]
    for out in outputs:
        out.graph = pred_logits[0].graph

    # Concatenate anchors
    anchors = torch.cat([a.tensor for a in anchors]).view(1, 1, -1)

    forward_hook(DetectionOutput(anchors), (deltas, logist), outputs)
    return outputs


def forward(model, forward, batched_inputs):
    return forward([{'image': batched_inputs}])


def preprocess_image(model, forward, inp):
    out = namedtuple('ImageList', ['tensor', 'image_sizes'])
    out.tensor = (inp[0]['image'] - model.pixel_mean) / model.pixel_std
    out.image_sizes = [out.tensor.shape[-2:]]
    return out


def detector_postprocess(results, output_height, output_width, mask_threshold=0.5):
    pass


# https://github.com/facebookresearch/detectron2/blob/master/detectron2/modeling/meta_arch/retinanet.py
class RetinaNet(object):
    def __init__(self):
        self.class_name = 'detectron2.modeling.meta_arch.retinanet.RetinaNet'

    def hook(self, new_func, model, old_func):
        return lambda *args: new_func(model, old_func, *args)

    def register_hook(self, model, is_dynamic):
        model.inference = self.hook(inference, model, model.inference)
        model.forward = self.hook(forward, model, model.forward)
        model.preprocess_image = self.hook(preprocess_image, model, model.preprocess_image)
        import detectron2
        detectron2.modeling.meta_arch.retinanet.detector_postprocess = detector_postprocess
