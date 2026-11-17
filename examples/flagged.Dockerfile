# A Dockerfile with unpinned base images.
FROM python
FROM node:latest
FROM alpine AS base
FROM ubuntu:latest AS builder
FROM golang:1.22
