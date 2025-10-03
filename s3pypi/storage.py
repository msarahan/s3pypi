from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import boto3
import botocore
from botocore.config import Config as BotoConfig
from mypy_boto3_s3.service_resource import Object

from s3pypi.index import Index
from s3pypi.locking import DynamoDBLocker


@dataclass
class S3Config:
    bucket: str
    prefix: Optional[str] = None
    profile: Optional[str] = None
    region: Optional[str] = None
    no_sign_request: bool = False
    endpoint_url: Optional[str] = None
    put_kwargs: Dict[str, str] = field(default_factory=dict)
    index_html: bool = False
    index_json: bool = False
    json_api_version: str = "1.0"
    locks_table: Optional[str] = None


class S3Storage:
    root = "/"
    _index_html = "index.html"
    _index_json = "index.json"

    def __init__(self, cfg: S3Config):
        session = boto3.Session(profile_name=cfg.profile, region_name=cfg.region)

        config = None
        if cfg.no_sign_request:
            config = BotoConfig(signature_version=botocore.session.UNSIGNED)  # type: ignore

        self.s3 = session.resource("s3", endpoint_url=cfg.endpoint_url, config=config)
        # For backward compatibility, use HTML index name when only HTML is enabled
        self.index_name = self._index_html if cfg.index_html else ""
        self.cfg = cfg

        self.lock = DynamoDBLocker.build(
            session,
            table_name=cfg.locks_table or f"{cfg.bucket}-locks",
            discover=not cfg.locks_table,
        )

    def _object(self, directory: str, filename: str) -> Object:
        parts = [directory, filename]
        if parts == [self.root, self.index_name]:
            parts = [p, self.index_name] if (p := self.cfg.prefix) else [self._index_html]
        elif self.cfg.prefix:
            parts.insert(0, self.cfg.prefix)
        return self.s3.Object(self.cfg.bucket, key="/".join(parts))

    def get_index(self, directory: str) -> Index:
        # Try JSON first if enabled, fall back to HTML
        if self.cfg.index_json:
            try:
                json_data = self._object(directory, self._index_json).get()["Body"].read()
                return Index.parse_json(json_data.decode())
            except botocore.exceptions.ClientError:
                pass  # JSON not found, try HTML
        
        # Try HTML index
        if self.cfg.index_html or self.index_name:
            try:
                html_data = self._object(directory, self.index_name or self._index_html).get()["Body"].read()
                return Index.parse(html_data.decode())
            except botocore.exceptions.ClientError:
                pass  # HTML not found
        
        return Index()

    @contextmanager
    def locked_index(self, directory: str) -> Iterator[Index]:
        with self.lock(directory):
            index = self.get_index(directory)
            yield index

            if index.filenames:
                self.put_index(directory, index)
            else:
                # Delete both index types if they exist
                if self.cfg.index_html or self.index_name:
                    self.delete(directory, self.index_name or self._index_html)
                if self.cfg.index_json:
                    self.delete(directory, self._index_json)

    def list_directories(self) -> List[str]:
        prefix = f"{p}/" if (p := self.cfg.prefix) else ""
        return [
            d[len(prefix) :]
            for item in self.s3.meta.client.get_paginator("list_objects_v2")
            .paginate(Bucket=self.cfg.bucket, Delimiter="/", Prefix=prefix)
            .search("CommonPrefixes")
            if item and (d := item.get("Prefix"))
        ]

    def put_index(self, directory: str, index: Index) -> None:
        # Generate HTML index if enabled
        if self.cfg.index_html or self.index_name:
            self._object(directory, self.index_name or self._index_html).put(
                Body=index.to_html(),
                ContentType="text/html",
                CacheControl="public, must-revalidate, proxy-revalidate, max-age=0",
                **self.cfg.put_kwargs,  # type: ignore
            )
        
        # Generate JSON index if enabled
        if self.cfg.index_json:
            self._object(directory, self._index_json).put(
                Body=index.to_json(self.cfg.json_api_version),
                ContentType="application/vnd.pypi.simple.v1+json",
                CacheControl="public, must-revalidate, proxy-revalidate, max-age=0",
                **self.cfg.put_kwargs,  # type: ignore
            )

    def put_distribution(self, directory: str, local_path: Path) -> None:
        with open(local_path, mode="rb") as f:
            self._object(directory, local_path.name).put(
                Body=f,
                ContentType="application/x-gzip",
                **self.cfg.put_kwargs,  # type: ignore
            )

    def delete(self, directory: str, filename: str) -> None:
        self._object(directory, filename).delete()
