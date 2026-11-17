# Edge cases: lowercase from, a platform flag, a registry port,
# a digest-only image, an ARG tag, a split FROM line, and a FROM in a comment.
from debian:12-slim
FROM --platform=linux/amd64 nginx:1.25
FROM registry.example.com:5000/team/app:2.0
FROM redis@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
FROM $BASE_IMAGE
FROM python:3.12-slim \
  AS base
# FROM busybox
