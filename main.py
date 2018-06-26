from autocommand import autocommand
import aiohttp
import asyncio
import json
import collections

ISSUES_QUERY = '''
query($owner:String! $repo:String! $cursor:String) {
  repository(owner:$owner name:$repo) {
    issues(first:100 after:$cursor states:[OPEN]) {
      nodes {
        title
        url
        number
        labels(first:100) {
          nodes {
            name
          }
        }
        comments(last:1) {
          nodes {
            authorAssociation
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
'''


class Issue(collections.namedtuple("Issue", "title number url")):
	pass


async def get_issues(owner, repository, token, ignore_labels):
	headers = {
		"Authorization": "bearer {token}".format(token=token),
		"Accept": "application/json",
		"Content-Type": "application/json",
	}

	ignore_labels = {label.lower() for label in ignore_labels}

	async with aiohttp.ClientSession(headers=headers) as session:

		async def get_page(cursor):
			full_query = {
				"query": ISSUES_QUERY,
				"variables": {
					"owner": owner,
					"repo": repository,
					"cursor": cursor
				}
			}
			async with session.post("https://api.github.com/graphql", json=full_query) as response:
				data = await response.json()

			issues_data = data["data"]["repository"]["issues"]
			issues = issues_data["nodes"]
			pageInfo = issues_data["pageInfo"]
			cursor = pageInfo['endCursor'] if pageInfo['hasNextPage'] else None

			return (cursor, issues)

		request = get_page(None)

		while request is not None:
			(cursor, issues) = await request
			if cursor:
				request = asyncio.ensure_future(get_page(cursor))

				# Allow the next request to initiate, so i/o is happening in the
				# background
				await asyncio.sleep(0)
			else:
				request = None

			for issue in issues:
				# Check ignore_labels, commentor status
				if any(
					label["name"].lower() in ignore_labels
					for label in issue["labels"]["nodes"]
				):
					continue

				comments = issue["comments"]["nodes"]
				if comments and comments[0]["authorAssociation"] in ("MEMBER", "OWNER", "COLLABORATOR"):
					continue

				yield Issue(
					title=issue["title"].strip(),
					url=issue["url"],
					number=issue["number"],
				)


@autocommand(__name__, loop=True)
async def main(
	owner,
	repository,
	token=None,
	ignore_labels=""
):
	async for issue in get_issues(owner, repository, token, ignore_labels.split()):
		print("Issue {number}\t{title}".format(
			number=issue.number,
			title=issue.title,
		))
