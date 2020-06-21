FROM python:3.8-alpine as builder

RUN apk add --no-cache linux-headers g++ make

RUN pip wheel --wheel-dir=/root/wheels uvloop httptools

FROM python:3.8-alpine

COPY --from=builder /root/wheels /root/wheels

RUN pip install \
      --no-index \
      --find-links=/root/wheels \
      uvloop httptools

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

EXPOSE 80

COPY ./app /app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]