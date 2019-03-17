from collections import defaultdict
import numpy as np
import json

from .common import voc_ap, viou


def eval_detection_scores(gt_relations, pred_relations, viou_threshold):
    pred_relations = sorted(pred_relations, key=lambda x: x['score'], reverse=True)
    gt_detected = np.zeros((len(gt_relations),), dtype=bool)
    hit_scores = np.ones((len(pred_relations))) * -np.inf
    for pred_idx, pred_relation in enumerate(pred_relations):
        ov_max = -float('Inf')
        k_max = -1
        for gt_idx, gt_relation in enumerate(gt_relations):
            if not gt_detected[gt_idx] \
                    and tuple(pred_relation['triplet']) == tuple(gt_relation['triplet']):
                s_iou = viou(pred_relation['sub_traj'], pred_relation['duration'],
                             gt_relation['sub_traj'], gt_relation['duration'])
                o_iou = viou(pred_relation['obj_traj'], pred_relation['duration'],
                             gt_relation['obj_traj'], gt_relation['duration'])
                ov = min(s_iou, o_iou)
                if ov >= viou_threshold and ov > ov_max:
                    ov_max = ov
                    k_max = gt_idx
        if k_max >= 0:
            hit_scores[pred_idx] = pred_relation['score']
            gt_detected[k_max] = True
    tp = np.isfinite(hit_scores)
    fp = ~tp
    cum_tp = np.cumsum(tp).astype(np.float32)
    cum_fp = np.cumsum(fp).astype(np.float32)
    rec = cum_tp / np.maximum(len(gt_relations), np.finfo(np.float32).eps)
    prec = cum_tp / np.maximum(cum_tp + cum_fp, np.finfo(np.float32).eps)
    return prec, rec, hit_scores


def eval_tagging_scores(gt_relations, pred_relations):
    pred_relations = sorted(pred_relations, key=lambda x: x['score'], reverse=True)
    # ignore trajectories
    gt_triplets = set(tuple(r['triplet']) for r in gt_relations)
    pred_triplets = []
    hit_scores = []
    for r in pred_relations:
        triplet = tuple(r['triplet'])
        if triplet not in pred_triplets:
            pred_triplets.append(triplet)
            hit_scores.append(r['score'])
    hit_scores = np.asarray(hit_scores)
    for i, t in enumerate(pred_triplets):
        if t not in gt_triplets:
            hit_scores[i] = -np.inf
    tp = np.isfinite(hit_scores)
    fp = ~tp
    cum_tp = np.cumsum(tp).astype(np.float32)
    cum_fp = np.cumsum(fp).astype(np.float32)
    rec = cum_tp / np.maximum(len(gt_triplets), np.finfo(np.float32).eps)
    prec = cum_tp / np.maximum(cum_tp + cum_fp, np.finfo(np.float32).eps)
    return prec, rec, hit_scores


def evaluate_segs(groundtruth, prediction, base_on_gt=True, viou_threshold=0.5,
                  det_nreturns=[50, 100], tag_nreturns=[1, 5, 10]):
    """
    evaluate VRD on segments level
    :return:
    """
    if not base_on_gt:
        # base on prediction segments
        print('Computing average precision AP over {}({}) videos...'.format('prediction', len(prediction)))
        print('This evaluation is based segments, traversal on predictions...')
        seg_ap = dict()
        tot_scores = defaultdict(list)
        tot_tp = defaultdict(list)
        prec_at_n = defaultdict(list)
        tot_pred_relations = 0

        # split on segments
        for vid, pred_relations in prediction.items():
            if len(pred_relations) == 0:
                continue
            tot_pred_relations += len(pred_relations)
            gt_relations = groundtruth[vid]
            # generate each seg gt
            for each_gt_seg in gt_relations:

                # compute average precision and recalls in detection setting
                det_prec, det_rec, det_scores = eval_detection_scores(
                    [each_gt_seg], pred_relations, viou_threshold)
                seg_ap[vid] = voc_ap(det_rec, det_prec)
                tp = np.isfinite(det_scores)
                for nre in det_nreturns:
                    cut_off = min(nre, det_scores.size)
                    tot_scores[nre].append(det_scores[:cut_off])
                    tot_tp[nre].append(tp[:cut_off])
                # compute precisions in tagging setting
                tag_prec, _, _ = eval_tagging_scores([each_gt_seg], pred_relations)
                for nre in tag_nreturns:
                    cut_off = min(nre, tag_prec.size)
                    if cut_off > 0:
                        prec_at_n[nre].append(tag_prec[cut_off - 1])
                    else:
                        prec_at_n[nre].append(0.)
        # calculate mean ap for detection
        mean_ap = np.mean(list(seg_ap.values()))
        # calculate recall for detection
        rec_at_n = dict()
        for nre in det_nreturns:
            scores = np.concatenate(tot_scores[nre])
            tps = np.concatenate(tot_tp[nre])
            sort_indices = np.argsort(scores)[::-1]
            tps = tps[sort_indices]
            cum_tp = np.cumsum(tps).astype(np.float32)
            rec = cum_tp / np.maximum(tot_pred_relations, np.finfo(np.float32).eps)
            rec_at_n[nre] = rec[-1]
        # calculate mean precision for tagging
        mprec_at_n = dict()
        for nre in tag_nreturns:
            mprec_at_n[nre] = np.mean(prec_at_n[nre])
    else:
        print("What???")
        exit(0)

    # print scores
    print(
        'This result of evaluation is based on: {}'.format(
            '200 groundtruth test set' if base_on_gt else 'predictions'))
    print('detection mean AP (used in challenge): {}'.format(mean_ap))
    print('detection recall@50: {}'.format(rec_at_n[50]))
    print('detection recall@100: {}'.format(rec_at_n[100]))
    print('tagging precision@1: {}'.format(mprec_at_n[1]))
    print('tagging precision@5: {}'.format(mprec_at_n[5]))
    print('tagging precision@10: {}'.format(mprec_at_n[10]))
    return mean_ap, rec_at_n, mprec_at_n


def evaluate(groundtruth, prediction, base_on_gt=True, viou_threshold=0.5,
             det_nreturns=[50, 100], tag_nreturns=[1, 5, 10]):
    """
    evaluate visual relation detection and visual relation tagging.
    """
    if base_on_gt:
        print('Computing average precision AP over {}({}) videos...'.format('groundtruth', len(groundtruth)))
        video_ap = dict()
        tot_scores = defaultdict(list)
        tot_tp = defaultdict(list)
        prec_at_n = defaultdict(list)
        tot_gt_relations = 0
        for vid, gt_relations in groundtruth.items():
            if len(gt_relations) == 0:
                continue
            tot_gt_relations += len(gt_relations)
            predict_relations = prediction[vid]
            # compute average precision and recalls in detection setting
            det_prec, det_rec, det_scores = eval_detection_scores(
                gt_relations, predict_relations, viou_threshold)
            video_ap[vid] = voc_ap(det_rec, det_prec)
            tp = np.isfinite(det_scores)
            for nre in det_nreturns:
                cut_off = min(nre, det_scores.size)
                tot_scores[nre].append(det_scores[:cut_off])
                tot_tp[nre].append(tp[:cut_off])
            # compute precisions in tagging setting
            tag_prec, _, _ = eval_tagging_scores(gt_relations, predict_relations)
            for nre in tag_nreturns:
                cut_off = min(nre, tag_prec.size)
                if cut_off > 0:
                    prec_at_n[nre].append(tag_prec[cut_off - 1])
                else:
                    prec_at_n[nre].append(0.)
        # calculate mean ap for detection
        mean_ap = np.mean(list(video_ap.values()))
        # calculate recall for detection
        rec_at_n = dict()
        for nre in det_nreturns:
            scores = np.concatenate(tot_scores[nre])
            tps = np.concatenate(tot_tp[nre])
            sort_indices = np.argsort(scores)[::-1]
            tps = tps[sort_indices]
            cum_tp = np.cumsum(tps).astype(np.float32)
            rec = cum_tp / np.maximum(tot_gt_relations, np.finfo(np.float32).eps)
            rec_at_n[nre] = rec[-1]
        # calculate mean precision for tagging
        mprec_at_n = dict()
        for nre in tag_nreturns:
            mprec_at_n[nre] = np.mean(prec_at_n[nre])

    else:
        print('Computing average precision AP over {}({}) videos...'.format('prediction', len(prediction)))
        video_ap = dict()
        tot_scores = defaultdict(list)
        tot_tp = defaultdict(list)
        prec_at_n = defaultdict(list)
        tot_pred_relations = 0
        for vid, pred_relations in prediction.items():
            # print("Now evaluate video: ", vid)
            if len(pred_relations) == 0:
                continue
            tot_pred_relations += len(pred_relations)
            gt_relations = groundtruth[vid]
            # compute average precision and recalls in detection setting
            det_prec, det_rec, det_scores = eval_detection_scores(
                gt_relations, pred_relations, viou_threshold)
            video_ap[vid] = voc_ap(det_rec, det_prec)
            tp = np.isfinite(det_scores)
            for nre in det_nreturns:
                cut_off = min(nre, det_scores.size)
                tot_scores[nre].append(det_scores[:cut_off])
                tot_tp[nre].append(tp[:cut_off])
            # compute precisions in tagging setting
            tag_prec, _, _ = eval_tagging_scores(gt_relations, pred_relations)
            for nre in tag_nreturns:
                cut_off = min(nre, tag_prec.size)
                if cut_off > 0:
                    prec_at_n[nre].append(tag_prec[cut_off - 1])
                else:
                    prec_at_n[nre].append(0.)
        # calculate mean ap for detection
        mean_ap = np.mean(list(video_ap.values()))
        # calculate recall for detection
        rec_at_n = dict()
        for nre in det_nreturns:
            scores = np.concatenate(tot_scores[nre])
            tps = np.concatenate(tot_tp[nre])
            sort_indices = np.argsort(scores)[::-1]
            tps = tps[sort_indices]
            cum_tp = np.cumsum(tps).astype(np.float32)
            rec = cum_tp / np.maximum(tot_pred_relations, np.finfo(np.float32).eps)
            rec_at_n[nre] = rec[-1]
        # calculate mean precision for tagging
        mprec_at_n = dict()
        for nre in tag_nreturns:
            mprec_at_n[nre] = np.mean(prec_at_n[nre])

    # print scores
    print(
        'This result of evaluation is based on: {}'.format('200 groundtruth test set' if base_on_gt else 'predictions'))
    print('detection mean AP (used in challenge): {}'.format(mean_ap))
    print('detection recall@50: {}'.format(rec_at_n[50]))
    print('detection recall@100: {}'.format(rec_at_n[100]))
    print('tagging precision@1: {}'.format(mprec_at_n[1]))
    print('tagging precision@5: {}'.format(mprec_at_n[5]))
    print('tagging precision@10: {}'.format(mprec_at_n[10]))
    return mean_ap, rec_at_n, mprec_at_n
