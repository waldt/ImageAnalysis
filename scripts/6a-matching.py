#!/usr/bin/python

import sys
sys.path.insert(0, "/usr/local/opencv-2.4.11/lib/python2.7/site-packages/")

import argparse
import commands
import cv2
import fnmatch
import math
import numpy as np
import os.path
from progress.bar import Bar
import scipy.spatial

sys.path.append('../lib')
import Matcher
import Pose
import ProjectMgr
import SRTM

# working on matching features ...

parser = argparse.ArgumentParser(description='Keypoint projection.')
parser.add_argument('--project', required=True, help='project directory')
parser.add_argument('--matcher', default='FLANN',
                    choices=['FLANN', 'BF'])
parser.add_argument('--match-ratio', default=0.75, type=float,
                    help='match ratio')

args = parser.parse_args()

proj = ProjectMgr.ProjectMgr(args.project)
proj.load_image_info()
proj.load_features()
proj.undistort_keypoints()

# setup SRTM ground interpolator
ref = proj.ned_reference_lla
sss = SRTM.NEDGround( ref, 2000, 2000, 30 )

# project undistorted keypoints into NED space
camw, camh = proj.cam.get_image_params()
fx, fy, cu, cv, dist_coeffs, skew = proj.cam.get_calibration_params()
bar = Bar('Projecting keypoints to vectors:',
          max = len(proj.image_list))
for image in proj.image_list:
    # print "Projecting keypoints to vectors:", image.name
    scale = float(image.width) / float(camw)
    K = np.array([ [fx*scale, skew*scale, cu*scale],
                   [ 0,       fy  *scale, cv*scale],
                   [ 0,       0,          1       ] ], dtype=np.float32)
    IK = np.linalg.inv(K)
    quat = image.camera_pose['quat']
    image.vec_list = proj.projectVectors(IK, quat, image.uv_list)
    bar.next()
bar.finish()

# intersect keypoint vectors with srtm terrain
bar = Bar('Vector/terrain intersecting:',
          max = len(proj.image_list))
for image in proj.image_list:
    #print "Intersecting keypoint vectors with terrain:", image.name
    image.coord_list = sss.interpolate_vectors(image.camera_pose,
                                               image.vec_list)
    bar.next()
bar.finish()

# compute a bounding sphere for each image
bar = Bar('Compute bounding spheres:',
          max = len(proj.image_list))
for image in proj.image_list:
    sum = np.array([0.0, 0.0, 0.0])
    for p in image.coord_list:
        sum += p
    image.center = sum / len(image.coord_list)
    max_dist = 0.0
    for p in image.coord_list:
        dist = np.linalg.norm(image.center - p)
        if dist > max_dist:
            max_dist = dist
    image.radius = max_dist
    # print "center = %s radius = %.1f" % (image.center, image.radius)
    bar.next()
bar.finish()
        

# build kdtree() of 3d point locations for fast spacial nearest
# neighbor lookups.
bar = Bar('Construct KDTrees:',
          max = len(proj.image_list))
for image in proj.image_list:
    if len(image.coord_list):
        image.kdtree = scipy.spatial.KDTree(image.coord_list)
    else:
        image.kdtree = None

    #result = image.kdtree.query_ball_point(image.coord_list[0], 5.0)
    #p1 = image.coord_list[0]
    #print "ref =", p1
    #for i in result:
    #    p2 = image.coord_list[i]
    #    d1 = p1[0] - p2[0]
    #    d2 = p1[1] - p2[1]
    #    dist = math.sqrt(d1**2 + d2**2)
    #    print "dist=%.2f  coord=%s" % (dist, p2)

    bar.next()
bar.finish()

# fire up the matcher
m = Matcher.Matcher()
matcher_params = { 'matcher': args.matcher,
                   'match-ratio': args.match_ratio }
m.configure(proj.detector_params, proj.matcher_params)
m.robustGroupMatches(proj.image_list, filter="fundamental", review=False)
