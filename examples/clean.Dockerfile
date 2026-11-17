# A clean multi-stage Dockerfile — every base image pins a tag.
FROM python:3.12-slim AS base
FROM node:20-alpine AS build
FROM golang:1.22-bookworm AS builder
FROM scratch
FROM alpine:3.19
FROM ${BASE_IMAGE}
FROM redis:7.2@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
